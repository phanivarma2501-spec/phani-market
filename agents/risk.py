"""
agents/risk.py
AGENT 4: Risk Agent (Rule-based, NO LLM)

Pure math: Kelly Criterion sizing, correlation checks, portfolio limits.
No API calls, no LLM costs. Deterministic and fast.
"""

import math
from typing import Dict, List, Tuple
from loguru import logger

from config.settings import settings
from strategies.correlation import CorrelationDetector, detect_themes


class RiskAgent:
    """
    Agent 4: Rule-based risk management.
    Kelly Criterion + correlation + portfolio limits.
    Zero LLM cost.
    """

    def __init__(self):
        self.correlation = CorrelationDetector()

    def kelly_criterion(
        self,
        our_prob: float,
        market_price: float,
        confidence: float,
    ) -> Dict:
        """
        Calculate fractional Kelly bet size.
        Returns sizing details.
        """
        # Determine bet direction
        if our_prob > market_price:
            direction = "YES"
            bet_price = market_price
            p = our_prob
        elif our_prob < market_price:
            direction = "NO"
            bet_price = 1.0 - market_price
            p = 1.0 - our_prob
        else:
            return {
                "direction": "NONE",
                "full_kelly": 0.0,
                "fractional_kelly": 0.0,
                "position_pct": 0.0,
                "position_usd": 0.0,
                "edge": 0.0,
            }

        # Kelly: f = (bp - q) / b
        b = (1.0 / bet_price) - 1.0
        if b <= 0:
            return {
                "direction": direction,
                "full_kelly": 0.0,
                "fractional_kelly": 0.0,
                "position_pct": 0.0,
                "position_usd": 0.0,
                "edge": our_prob - market_price,
            }

        q = 1.0 - p
        full_kelly = max(0.0, (b * p - q) / b)

        # Scale by confidence: only bet more when very confident
        conf_scaler = max(0.0, (confidence - 0.65) / (1.0 - 0.65))
        fractional = full_kelly * settings.KELLY_FRACTION * conf_scaler

        position_pct = min(fractional, settings.MAX_POSITION_PCT)

        return {
            "direction": direction,
            "full_kelly": round(full_kelly, 4),
            "fractional_kelly": round(fractional, 4),
            "position_pct": round(position_pct, 4),
            "position_usd": 0.0,  # Filled by pipeline with actual capital
            "edge": round(our_prob - market_price, 4),
        }

    def check_correlation(
        self,
        open_positions: List[Dict],
        market_question: str,
        proposed_size_usd: float,
        total_capital: float,
    ) -> Dict:
        """Check if trade would create excessive correlation."""
        should_trade, reason = self.correlation.check_before_trade(
            open_positions, market_question, proposed_size_usd, total_capital
        )

        themes = detect_themes(market_question)

        # Calculate existing theme exposure
        theme_exposures = {}
        for theme in themes:
            exposure = sum(
                p.get("size_usd", 0) for p in open_positions
                if theme in detect_themes(p.get("market_question", ""))
            )
            theme_exposures[theme] = round(exposure, 2)

        return {
            "approved": should_trade,
            "reason": reason,
            "themes_detected": themes,
            "theme_exposures": theme_exposures,
        }

    def portfolio_limits(
        self,
        open_positions: List[Dict],
        total_capital: float,
    ) -> Dict:
        """Check portfolio-level risk limits."""
        deployed = sum(p.get("size_usd", 0) for p in open_positions)
        deployed_pct = deployed / total_capital if total_capital > 0 else 0

        return {
            "total_deployed": round(deployed, 2),
            "deployed_pct": round(deployed_pct, 4),
            "remaining_capital": round(total_capital - deployed, 2),
            "at_capacity": deployed_pct >= 0.95,
            "position_count": len(open_positions),
        }

    async def run(
        self,
        market_question: str,
        our_probability: float,
        market_price: float,
        confidence: float,
        open_positions: List[Dict],
        total_capital: float,
    ) -> Dict:
        """
        Run the Risk Agent. Pure math, no LLM.
        Returns sizing, correlation check, and portfolio status.
        """
        # Kelly sizing
        kelly = self.kelly_criterion(our_probability, market_price, confidence)
        kelly["position_usd"] = round(total_capital * kelly["position_pct"], 2)

        # Correlation check
        correlation = self.check_correlation(
            open_positions, market_question,
            kelly["position_usd"], total_capital,
        )

        # Portfolio limits
        portfolio = self.portfolio_limits(open_positions, total_capital)

        # Final risk verdict
        approved = True
        block_reasons = []

        if not correlation["approved"]:
            approved = False
            block_reasons.append(correlation["reason"])

        if portfolio["at_capacity"]:
            approved = False
            block_reasons.append("Portfolio at capacity (>95% deployed)")

        if kelly["position_usd"] < 5.0:
            approved = False
            block_reasons.append(f"Position too small (${kelly['position_usd']:.2f})")

        result = {
            "agent": "risk",
            "approved": approved,
            "block_reasons": block_reasons,
            "kelly": kelly,
            "correlation": correlation,
            "portfolio": portfolio,
        }

        logger.debug(
            f"Risk Agent: {market_question[:50]} | "
            f"{'APPROVED' if approved else 'BLOCKED'} | "
            f"kelly={kelly['position_pct']:.2%} ${kelly['position_usd']:.0f} | "
            f"deployed={portfolio['deployed_pct']:.0%}"
        )
        return result
