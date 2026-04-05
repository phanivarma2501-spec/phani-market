"""
agents/pipeline.py
Orchestrates the 5-agent pipeline for each market.

Flow:
  Market + News --> [Research Agent] --> research_brief
                                            |
  research_brief --> [Reasoning Agent] --> probability + reasoning
                                            |
  reasoning + research --> [Devil's Advocate] --> challenges + adjustments
                                            |
  all data --> [Risk Agent] --> kelly sizing + correlation + limits
                                            |
  all outputs --> [Decision Agent] --> final BUY/SELL/HOLD
"""

from typing import List, Optional
from loguru import logger
from datetime import datetime, timedelta

from agents.research import ResearchAgent
from agents.reasoning import ReasoningAgent
from agents.devils_advocate import DevilsAdvocateAgent
from agents.risk import RiskAgent
from agents.decision import DecisionAgent

from core.models import (
    PolymarketMarket, NewsItem, ReasoningResult,
    ReasoningStep, SignalStrength,
)
from config.settings import settings


class AgentPipeline:
    """
    Orchestrates the 5-agent reasoning pipeline.
    Each market goes through all 5 agents sequentially.
    """

    def __init__(self):
        self.research = ResearchAgent()
        self.reasoning = ReasoningAgent()
        self.devils_advocate = DevilsAdvocateAgent()
        self.risk = RiskAgent()
        self.decision = DecisionAgent()

    async def run(
        self,
        market: PolymarketMarket,
        news_items: List[NewsItem],
        cross_platform_context: str = "",
        open_positions: list = None,
        total_capital: float = 10_000.0,
    ) -> Optional[ReasoningResult]:
        """
        Run the full 5-agent pipeline for one market.
        Returns a ReasoningResult compatible with the existing paper trader.
        """
        open_positions = open_positions or []

        try:
            # ── Agent 1: Research ─────────────────────────────────────────
            research_brief = await self.research.run(
                market, news_items, cross_platform_context
            )

            # ── Agent 2: Reasoning (R1) ──────────────────────────────────
            reasoning_output = await self.reasoning.run(market, research_brief)

            # ── Agent 3: Devil's Advocate (R1) ───────────────────────────
            da_output = await self.devils_advocate.run(
                market, reasoning_output, research_brief
            )

            # Apply DA adjustments to get consensus probability
            da_prob_adj = da_output.get("suggested_probability_adjustment", 0)
            da_conf_adj = da_output.get("suggested_confidence_adjustment", 0)
            adjusted_prob = max(0.01, min(0.99,
                reasoning_output["calibrated_probability"] + da_prob_adj
            ))
            adjusted_conf = max(0.0, min(1.0,
                reasoning_output["confidence"] + da_conf_adj
            ))

            # ── Agent 4: Risk (rule-based) ───────────────────────────────
            risk_output = await self.risk.run(
                market_question=market.question,
                our_probability=adjusted_prob,
                market_price=market.yes_price,
                confidence=adjusted_conf,
                open_positions=open_positions,
                total_capital=total_capital,
            )

            # ── Agent 5: Decision ────────────────────────────────────────
            decision = await self.decision.run(
                market, research_brief, reasoning_output,
                da_output, risk_output,
            )

            # ── Build ReasoningResult (backward compatible) ──────────────
            signal = decision["signal"]
            final_prob = decision["final_probability"]
            final_conf = decision["final_confidence"]
            edge = final_prob - market.yes_price

            # Build reasoning steps from all agents
            steps = []
            # Research summary step
            steps.append(ReasoningStep(
                step_name="research",
                question="What does the available evidence show?",
                answer=research_brief.get("research_summary", ""),
                probability_estimate=None,
                confidence=None,
            ))
            # Reasoning steps
            for s in reasoning_output.get("steps", []):
                steps.append(ReasoningStep(
                    step_name=s.get("step", "reasoning"),
                    question=s.get("step", ""),
                    answer=s.get("analysis", ""),
                    probability_estimate=s.get("probability", None),
                ))
            # DA step
            steps.append(ReasoningStep(
                step_name="devils_advocate",
                question="What could be wrong with this estimate?",
                answer=da_output.get("dissent_summary", ""),
                probability_estimate=adjusted_prob,
                confidence=adjusted_conf,
            ))
            # Decision step
            steps.append(ReasoningStep(
                step_name="decision",
                question="Final multi-agent decision",
                answer=decision.get("reasoning", ""),
                probability_estimate=final_prob,
                confidence=final_conf,
            ))

            kelly = risk_output.get("kelly", {})

            result = ReasoningResult(
                market_condition_id=market.condition_id,
                market_question=market.question,
                our_probability=round(final_prob, 4),
                market_probability=market.yes_price,
                edge=round(edge, 4),
                confidence=round(final_conf, 3),
                signal=signal,
                steps=steps,
                news_items_used=[n.url for n in news_items[:6]],
                base_rate_used=reasoning_output.get("base_rate_note", ""),
                reference_class=reasoning_output.get("base_rate_note", ""),
                raw_llm_probability=reasoning_output.get("raw_probability", 0.5),
                calibration_adjustment=reasoning_output.get("calibration_adjustment", 0),
                calibration_note=(
                    f"5-agent pipeline | "
                    f"Research={research_brief.get('news_sentiment', 'n/a')} | "
                    f"Reasoning={reasoning_output.get('calibrated_probability', 0):.1%} | "
                    f"DA_adj={da_prob_adj:+.1%} | "
                    f"Decision={signal.value}"
                ),
                kelly_fraction=kelly.get("full_kelly", 0),
                suggested_position_pct=kelly.get("position_pct", 0),
                suggested_position_usd=decision.get("position_size_usd", 0),
                valid_until=datetime.utcnow() + timedelta(
                    minutes=settings.REASONING_SCAN_INTERVAL_MINUTES
                ),
            )

            logger.info(
                f"Pipeline: '{market.question[:50]}' | "
                f"Our P: {final_prob:.1%} vs Market: {market.yes_price:.1%} | "
                f"Edge: {edge:+.1%} | Conf: {final_conf:.0%} | "
                f"Signal: {signal.value} | "
                f"Agents: {decision.get('agent_agreement', '?')}"
            )
            return result

        except Exception as e:
            logger.error(f"Pipeline failed for '{market.question[:50]}': {e}")
            return None
