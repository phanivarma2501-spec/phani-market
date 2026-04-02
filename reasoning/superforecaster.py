"""
reasoning/superforecaster.py

THE CORE DIFFERENTIATOR — Structured reasoning engine using Claude.

Every other bot asks an LLM: "What's the probability?"
We do it properly: base rates → reference class → inside view →
outside view → news adjustment → calibration → confidence banding.

This is Tetlock's superforecasting methodology implemented as an
AI reasoning pipeline. What makes us different from every open-source
Polymarket bot that exists.
"""

import anthropic
import json
import math
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from loguru import logger

from core.models import (
    PolymarketMarket, NewsItem, ReasoningResult,
    ReasoningStep, SignalStrength, Domain
)
from config.settings import settings


# ── Probability calibration ──────────────────────────────────────────────────
def platt_scale(p: float, scale: float = 0.7) -> float:
    """
    Recalibrate LLM probability estimates using Platt scaling.
    LLMs are systematically biased toward 0.5 due to RLHF training.
    This compresses extreme estimates toward the base rate.
    From: Polymarket Signal Agent devpost research.
    """
    p = max(0.01, min(0.99, p))
    logit = math.log(p / (1 - p))
    calibrated_logit = scale * logit
    return 1 / (1 + math.exp(-calibrated_logit))


# ── Domain base rates ─────────────────────────────────────────────────────────
DOMAIN_BASE_RATES = {
    Domain.CRYPTO: {
        "price_up_30d": (0.52, "crypto_price_targets",
                         "BTC/ETH price up in any 30-day window historically ~52%"),
        "major_hack": (0.15, "crypto_security_events",
                       "Major DeFi hack in any quarter ~15%"),
        "regulatory_action": (0.20, "regulatory_events",
                              "SEC/CFTC action in any quarter ~20%"),
        "default": (0.50, "crypto_prediction_market",
                    "Using market implied probability as prior"),
    },
    Domain.POLITICS: {
        "incumbent_wins": (0.65, "electoral_outcomes",
                           "Incumbent win rate historically ~65%"),
        "policy_passed": (0.40, "legislation_outcomes",
                          "Major policy bill passage rate ~40%"),
        "polling_leader_wins": (0.70, "polling_accuracy",
                                "Polling leader wins election ~70%"),
        "default": (0.50, "political_prediction_market",
                    "Using market implied probability as prior"),
    },
    Domain.ECONOMICS: {
        "fed_rate_cut": (0.45, "fed_rate_decisions",
                         "Fed rate cut at next meeting ~45% (2025-2026 base)"),
        "inflation_above_target": (0.55, "inflation_data",
                                   "CPI above 2.5% in any month ~55%"),
        "recession_12m": (0.20, "recession_prediction",
                          "NBER recession declared in next 12 months ~20%"),
        "gdp_beats": (0.50, "gdp_data",
                      "GDP beats consensus estimate ~50%"),
        "default": (0.50, "economic_prediction_market",
                    "Using market implied probability as prior"),
    },
}


SUPERFORECASTING_PROMPT = """You are an expert superforecaster applying the Tetlock methodology.
Estimate the probability this Polymarket prediction market resolves YES.

## Market Details
Question: {question}
Description: {description}
Current market implied probability: {market_price:.1%}
Days until resolution: {days_to_resolution}
Domain: {domain}
Resolution source: {resolution_source}

## Base Rate Anchor
Reference class: {reference_class}
Base rate for this event type: {base_rate:.1%}
Base rate note: {base_rate_note}

## Recent Relevant News
{news_context}

## Instructions
Apply all 6 superforecasting steps. Respond ONLY with valid JSON — no other text, no markdown.

{{
  "steps": [
    {{
      "step_name": "reference_class",
      "question": "What is the best reference class? What similar events resolved YES historically?",
      "answer": "<your analysis>",
      "probability_estimate": <0.0-1.0 or null>
    }},
    {{
      "step_name": "base_rate",
      "question": "What base rate applies? How does the provided base rate compare to your own assessment?",
      "answer": "<your analysis including specific base rate used>",
      "probability_estimate": <0.0-1.0>
    }},
    {{
      "step_name": "inside_view",
      "question": "What case-specific factors push probability above or below base rate?",
      "answer": "<specific current data, events, market structure — concrete, not vague>",
      "probability_estimate": <0.0-1.0>
    }},
    {{
      "step_name": "outside_view",
      "question": "What systemic factors, biases or market dynamics should adjust the estimate?",
      "answer": "<resolution ambiguity, manipulation risk, timing effects, overconfidence bias>",
      "probability_estimate": <0.0-1.0>
    }},
    {{
      "step_name": "news_adjustment",
      "question": "How does the recent news change the probability? Which item matters most?",
      "answer": "<specific impact of each relevant news item, direction and magnitude>",
      "probability_estimate": <0.0-1.0>
    }},
    {{
      "step_name": "synthesis",
      "question": "Final synthesis: how did you weight each step? What are the key uncertainties?",
      "answer": "<weighting rationale, uncertainties, final reasoning>",
      "probability_estimate": <0.0-1.0>,
      "confidence": <0.0-1.0>
    }}
  ],
  "final_probability": <0.0-1.0>,
  "confidence": <0.0-1.0>,
  "reference_class_used": "<string>",
  "base_rate_used": "<string>",
  "key_uncertainties": ["<uncertainty 1>", "<uncertainty 2>"],
  "relevant_news_indices": [<0-based index of most relevant news items>]
}}

Critical rules:
- Be precise. Use 0.43 not 0.50 unless genuinely uncertain.
- Confidence >= 0.75 = strong evidence. Confidence < 0.65 = HOLD (don't signal).
- Do NOT anchor to the current market price. Form your estimate independently first.
- If information is insufficient, set confidence below 0.60.
- News from the last 24h should carry 2-3x weight of older news."""


class SuperForecaster:
    """
    Structured reasoning engine — the core differentiator.

    Uses Claude to perform 6-step Tetlock superforecasting,
    producing calibrated probability estimates with confidence bands.
    This is what no other Polymarket bot does properly.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.REASONING_MODEL

    def _get_base_rate(
        self, market: PolymarketMarket
    ) -> Tuple[float, str, str]:
        """Match market to the most appropriate domain base rate."""
        question = market.question.lower()
        domain_rates = DOMAIN_BASE_RATES.get(market.domain, {})

        # Crypto domain matching
        if market.domain == Domain.CRYPTO:
            if any(w in question for w in ["above", "reach", "hit", "over", "$", "price", "high"]):
                rate, cls, note = domain_rates["price_up_30d"]
                return rate, cls, note
            if any(w in question for w in ["hack", "exploit", "attack", "breach"]):
                rate, cls, note = domain_rates["major_hack"]
                return rate, cls, note
            if any(w in question for w in ["sec", "cftc", "ban", "regulate", "illegal"]):
                rate, cls, note = domain_rates["regulatory_action"]
                return rate, cls, note

        # Politics domain matching
        elif market.domain == Domain.POLITICS:
            if any(w in question for w in ["win", "elected", "defeat", "election", "vote"]):
                rate, cls, note = domain_rates["incumbent_wins"]
                return rate, cls, note
            if any(w in question for w in ["pass", "bill", "act", "legislation", "law"]):
                rate, cls, note = domain_rates["policy_passed"]
                return rate, cls, note

        # Economics domain matching
        elif market.domain == Domain.ECONOMICS:
            if any(w in question for w in ["rate cut", "fed", "fomc", "bps", "basis point"]):
                rate, cls, note = domain_rates["fed_rate_cut"]
                return rate, cls, note
            if any(w in question for w in ["inflation", "cpi", "pce", "prices"]):
                rate, cls, note = domain_rates["inflation_above_target"]
                return rate, cls, note
            if any(w in question for w in ["recession", "gdp negative", "contraction"]):
                rate, cls, note = domain_rates["recession_12m"]
                return rate, cls, note
            if any(w in question for w in ["gdp", "growth", "economy"]):
                rate, cls, note = domain_rates["gdp_beats"]
                return rate, cls, note

        # Fallback: use market price as prior
        return market.yes_price, "prediction_market_prior", \
               f"Using market implied probability as prior: {market.yes_price:.1%}"

    def _format_news_context(self, news_items: List[NewsItem]) -> str:
        """Format news for the prompt, ordered by relevance."""
        if not news_items:
            return "No recent relevant news found. Rely heavily on base rates and reference class."

        lines = []
        for i, item in enumerate(news_items[:6]):
            age_str = ""
            if item.published_at:
                hours_ago = (datetime.utcnow() - item.published_at).total_seconds() / 3600
                if hours_ago < 24:
                    age_str = f" [{int(hours_ago)}h ago — HIGH WEIGHT]"
                elif hours_ago < 72:
                    age_str = f" [{int(hours_ago/24)}d ago]"
                else:
                    age_str = " [older]"

            lines.append(
                f"[{i}] {item.source}{age_str} | Relevance: {item.relevance_score:.0%}\n"
                f"    {item.title}\n"
                f"    {(item.summary or '')[:200]}"
            )
        return "\n\n".join(lines)

    def _calculate_kelly(
        self,
        our_prob: float,
        market_price: float,
        confidence: float,
        starting_capital: float = 10_000.0
    ) -> Tuple[float, float, float]:
        """
        Fractional Kelly sizing with confidence band scaling.
        Handles both BUY (YES) and SELL (NO) directions.
        Returns: (full_kelly, position_pct, position_usd)
        """
        # Determine direction: BUY YES or BUY NO
        if our_prob > market_price:
            # BUY YES: we think YES is underpriced
            bet_price = market_price
            p = our_prob
        elif our_prob < market_price:
            # BUY NO: we think NO is underpriced (YES is overpriced)
            bet_price = 1.0 - market_price
            p = 1.0 - our_prob
        else:
            return 0.0, 0.0, 0.0

        # Kelly formula: f = (bp - q) / b
        b = (1.0 / bet_price) - 1.0
        if b <= 0:
            return 0.0, 0.0, 0.0

        q = 1.0 - p
        full_kelly = max(0.0, (b * p - q) / b)

        # Scale by confidence: only bet more when very confident
        conf_scaler = max(0.0, (confidence - 0.65) / (1.0 - 0.65))
        fractional = full_kelly * settings.KELLY_FRACTION * conf_scaler

        position_pct = min(fractional, settings.MAX_POSITION_PCT)
        position_usd = starting_capital * position_pct

        return round(full_kelly, 4), round(position_pct, 4), round(position_usd, 2)

    def _determine_signal(
        self,
        edge: float,
        confidence: float,
        our_prob: float,
        market_price: float
    ) -> SignalStrength:
        """Map edge + confidence to a signal strength."""
        if confidence < settings.REASONING_CONFIDENCE_MIN:
            return SignalStrength.HOLD

        abs_edge = abs(edge)

        if our_prob > market_price:  # BUY direction
            if abs_edge >= settings.HIGH_CONFIDENCE_EDGE and confidence >= 0.75:
                return SignalStrength.STRONG_BUY
            elif abs_edge >= settings.MIN_EDGE_TO_FLAG:
                return SignalStrength.BUY
            else:
                return SignalStrength.HOLD
        else:  # SELL direction
            if abs_edge >= settings.HIGH_CONFIDENCE_EDGE and confidence >= 0.75:
                return SignalStrength.STRONG_SELL
            elif abs_edge >= settings.MIN_EDGE_TO_FLAG:
                return SignalStrength.SELL
            else:
                return SignalStrength.HOLD

    def _parse_llm_response(self, raw_text: str) -> dict:
        """Parse JSON from LLM response, handling minor formatting issues."""
        # Strip any accidental markdown fences
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip().rstrip("```").strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Try to find JSON object in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except Exception:
                    pass
            raise ValueError(f"Could not parse LLM JSON: {e}\nRaw: {text[:500]}")

    async def reason_about_market(
        self,
        market: PolymarketMarket,
        news_items: List[NewsItem],
        starting_capital: float = 10_000.0,
        extra_context: str = "",
    ) -> Optional[ReasoningResult]:
        """
        Core method: run structured superforecasting on one market.
        Returns ReasoningResult or None if reasoning fails/insufficient confidence.
        """
        base_rate, reference_class, base_rate_note = self._get_base_rate(market)
        news_context = self._format_news_context(news_items)

        # Append cross-platform price data if available
        if extra_context:
            news_context = news_context + "\n" + extra_context

        prompt = SUPERFORECASTING_PROMPT.format(
            question=market.question,
            description=(market.description or "")[:400],
            market_price=market.yes_price,
            days_to_resolution=market.days_to_resolution or "unknown",
            domain=market.domain.value,
            resolution_source=market.resolution_source or "unspecified",
            reference_class=reference_class,
            base_rate=base_rate,
            base_rate_note=base_rate_note,
            news_context=news_context,
        )

        try:
            logger.debug(f"Reasoning about: {market.question[:60]}...")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text
            data = self._parse_llm_response(raw_text)

            # Extract core outputs
            raw_prob = float(data.get("final_probability", market.yes_price))
            confidence = float(data.get("confidence", 0.5))

            # Apply Platt scaling calibration
            calibrated_prob = platt_scale(raw_prob)
            calibration_adj = calibrated_prob - raw_prob

            # Calculate edge
            edge = calibrated_prob - market.yes_price

            # Determine signal
            signal = self._determine_signal(edge, confidence, calibrated_prob, market.yes_price)

            # Kelly sizing
            full_kelly, position_pct, position_usd = self._calculate_kelly(
                calibrated_prob, market.yes_price, confidence, starting_capital
            )

            # Parse reasoning steps
            steps = []
            for s in data.get("steps", []):
                steps.append(ReasoningStep(
                    step_name=s.get("step_name", ""),
                    question=s.get("question", ""),
                    answer=s.get("answer", ""),
                    probability_estimate=s.get("probability_estimate"),
                    confidence=s.get("confidence"),
                ))

            # Extract news URLs used
            relevant_indices = data.get("relevant_news_indices", [])
            news_used = [
                news_items[i].url for i in relevant_indices
                if isinstance(i, int) and i < len(news_items)
            ]

            result = ReasoningResult(
                market_condition_id=market.condition_id,
                market_question=market.question,
                our_probability=round(calibrated_prob, 4),
                market_probability=market.yes_price,
                edge=round(edge, 4),
                confidence=round(confidence, 3),
                signal=signal,
                steps=steps,
                news_items_used=news_used,
                base_rate_used=data.get("base_rate_used", base_rate_note),
                reference_class=data.get("reference_class_used", reference_class),
                raw_llm_probability=round(raw_prob, 4),
                calibration_adjustment=round(calibration_adj, 4),
                calibration_note=f"Platt scaling applied (scale=0.7): {raw_prob:.3f} → {calibrated_prob:.3f}",
                kelly_fraction=full_kelly,
                suggested_position_pct=position_pct,
                suggested_position_usd=position_usd,
                valid_until=datetime.utcnow() + timedelta(minutes=settings.REASONING_SCAN_INTERVAL_MINUTES),
            )

            logger.info(
                f"Reasoned: '{market.question[:50]}' | "
                f"Our P: {calibrated_prob:.1%} vs Market: {market.yes_price:.1%} | "
                f"Edge: {edge:+.1%} | Conf: {confidence:.0%} | Signal: {signal.value}"
            )
            return result

        except Exception as e:
            logger.error(f"Reasoning failed for '{market.question[:50]}': {e}")
            return None
