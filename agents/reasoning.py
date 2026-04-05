"""
agents/reasoning.py
AGENT 2: Reasoning Agent (DeepSeek V3/R1)

Performs structured Tetlock superforecasting using the research brief.

Prompt split for prefix caching:
  SYSTEM_PROMPT (static, cached) — methodology + output format + rules
  USER_TEMPLATE (variable) — market data + research brief
"""

import math
from typing import Optional
from loguru import logger

from agents.base import call_llm_json
from core.models import PolymarketMarket, Domain
from config.settings import settings


# Domain base rates for anchoring
DOMAIN_BASE_RATES = {
    Domain.CRYPTO: {
        "price_target": (0.52, "BTC/ETH price up in any 30-day window ~52%"),
        "hack": (0.15, "Major DeFi hack in any quarter ~15%"),
        "regulation": (0.20, "SEC/CFTC action in any quarter ~20%"),
        "default": (0.50, "Market implied probability as prior"),
    },
    Domain.POLITICS: {
        "incumbent": (0.65, "Incumbent win rate ~65%"),
        "legislation": (0.40, "Major bill passage rate ~40%"),
        "polling_leader": (0.70, "Polling leader wins ~70%"),
        "default": (0.50, "Market implied probability as prior"),
    },
    Domain.ECONOMICS: {
        "fed_cut": (0.45, "Fed rate cut at meeting ~45%"),
        "inflation": (0.55, "CPI above 2.5% in any month ~55%"),
        "recession": (0.20, "Recession in next 12 months ~20%"),
        "default": (0.50, "Market implied probability as prior"),
    },
}

BASE_RATE_KEYWORDS = {
    Domain.CRYPTO: {
        "price_target": ["above", "reach", "hit", "over", "$", "price", "high"],
        "hack": ["hack", "exploit", "attack", "breach"],
        "regulation": ["sec", "cftc", "ban", "regulate"],
    },
    Domain.POLITICS: {
        "incumbent": ["win", "elected", "defeat", "election", "vote"],
        "legislation": ["pass", "bill", "act", "legislation", "law"],
    },
    Domain.ECONOMICS: {
        "fed_cut": ["rate cut", "fed", "fomc", "basis point"],
        "inflation": ["inflation", "cpi", "pce", "prices"],
        "recession": ["recession", "gdp negative", "contraction"],
    },
}


# Static instructions — CACHED by DeepSeek across all calls
SYSTEM_PROMPT = """You are an expert superforecaster applying the Tetlock methodology.
A Research Agent has prepared a brief. Use it to estimate the probability this market resolves YES.

Apply the 6 superforecasting steps. Think deeply about each step.
Respond ONLY with valid JSON:

{
  "steps": [
    {"step": "reference_class", "analysis": "<what similar events resolved YES historically?>", "probability": <0.0-1.0>},
    {"step": "base_rate", "analysis": "<how does the base rate apply here?>", "probability": <0.0-1.0>},
    {"step": "inside_view", "analysis": "<case-specific factors from the research brief>", "probability": <0.0-1.0>},
    {"step": "outside_view", "analysis": "<systemic biases, market dynamics, timing>", "probability": <0.0-1.0>},
    {"step": "news_adjustment", "analysis": "<how recent news shifts the estimate>", "probability": <0.0-1.0>},
    {"step": "synthesis", "analysis": "<weighting rationale and final reasoning>", "probability": <0.0-1.0>}
  ],
  "final_probability": <0.0-1.0>,
  "confidence": <0.0-1.0>,
  "key_drivers": ["<top 3 factors driving this estimate>"],
  "assumptions": ["<critical assumptions that could be wrong>"]
}

Rules:
- Be precise: 0.43 not 0.50 unless genuinely uncertain
- Do NOT anchor to market price. Form your estimate independently.
- Confidence >= 0.75 = strong evidence. < 0.65 = insufficient.
- If research quality is low, reduce confidence accordingly."""

# Variable data — changes every call
USER_TEMPLATE = """## Market
Question: {question}
Current market price: {market_price:.1%}
Days until resolution: {days_to_resolution}
Domain: {domain}

## Base Rate Anchor
Reference class: {base_rate_note}
Base rate: {base_rate:.1%}

## Research Brief
Key facts: {key_facts}
Bullish factors: {bullish_factors}
Bearish factors: {bearish_factors}
News sentiment: {news_sentiment}
Information quality: {info_quality}
Cross-platform: {cross_platform}
Key uncertainties: {uncertainties}
Summary: {research_summary}"""


def platt_scale(p: float, scale: float = 0.7) -> float:
    """Calibrate LLM probability — compress toward base rate."""
    p = max(0.01, min(0.99, p))
    logit = math.log(p / (1 - p))
    return 1 / (1 + math.exp(-scale * logit))


class ReasoningAgent:
    """Agent 2: Deep probability estimation using Tetlock methodology."""

    def __init__(self):
        self.model = settings.REASONING_MODEL

    def _get_base_rate(self, market: PolymarketMarket) -> tuple:
        question = market.question.lower()
        domain_rates = DOMAIN_BASE_RATES.get(market.domain, {})
        keywords = BASE_RATE_KEYWORDS.get(market.domain, {})

        for category, kws in keywords.items():
            if any(w in question for w in kws):
                rate, note = domain_rates[category]
                return rate, note

        rate, note = domain_rates.get("default", (0.50, "Using market prior"))
        return rate, note

    async def run(self, market: PolymarketMarket, research_brief: dict) -> dict:
        base_rate, base_rate_note = self._get_base_rate(market)

        user_msg = USER_TEMPLATE.format(
            question=market.question,
            market_price=market.yes_price,
            days_to_resolution=market.days_to_resolution or "unknown",
            domain=market.domain.value,
            base_rate=base_rate,
            base_rate_note=base_rate_note,
            key_facts="; ".join(research_brief.get("key_facts", [])[:6]),
            bullish_factors="; ".join(research_brief.get("bullish_factors", [])[:4]),
            bearish_factors="; ".join(research_brief.get("bearish_factors", [])[:4]),
            news_sentiment=research_brief.get("news_sentiment", "neutral"),
            info_quality=research_brief.get("information_quality", "low"),
            cross_platform=research_brief.get("cross_platform_consensus", "no data"),
            uncertainties="; ".join(research_brief.get("key_uncertainties", [])),
            research_summary=research_brief.get("research_summary", "No research available."),
        )

        try:
            data = call_llm_json(
                model=self.model,
                prompt=user_msg,
                system_prompt=SYSTEM_PROMPT,
                max_tokens=2000,
                temperature=0.2,
            )

            raw_prob = float(data.get("final_probability", 0.5))
            confidence = float(data.get("confidence", 0.5))
            calibrated_prob = platt_scale(raw_prob)

            result = {
                "agent": "reasoning",
                "raw_probability": round(raw_prob, 4),
                "calibrated_probability": round(calibrated_prob, 4),
                "confidence": round(confidence, 3),
                "base_rate": base_rate,
                "base_rate_note": base_rate_note,
                "calibration_adjustment": round(calibrated_prob - raw_prob, 4),
                "steps": data.get("steps", []),
                "key_drivers": data.get("key_drivers", []),
                "assumptions": data.get("assumptions", []),
            }

            logger.debug(
                f"Reasoning Agent: {market.question[:50]} | "
                f"raw={raw_prob:.1%} cal={calibrated_prob:.1%} conf={confidence:.0%}"
            )
            return result

        except Exception as e:
            logger.error(f"Reasoning Agent failed for '{market.question[:50]}': {e}")
            raise
