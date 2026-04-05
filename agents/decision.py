"""
agents/decision.py
AGENT 5: Decision Agent (DeepSeek V3)

Final arbiter. Synthesizes all 4 agent outputs into a single
actionable decision: BUY, SELL, or HOLD with exact sizing.

Prompt split for prefix caching:
  SYSTEM_PROMPT (static, cached) — decision role + output format + rules
  USER_TEMPLATE (variable) — all agent outputs for this market
"""

from loguru import logger

from agents.base import call_llm_json
from core.models import PolymarketMarket, SignalStrength
from config.settings import settings


# Static instructions — CACHED by DeepSeek across all calls
SYSTEM_PROMPT = """You are the final decision-maker for a prediction market trading bot.
Four specialist agents have analyzed this market. Synthesize their outputs into ONE decision.

Respond ONLY with valid JSON:
{
  "decision": "STRONG_BUY" or "BUY" or "HOLD" or "SELL" or "STRONG_SELL",
  "final_probability": <0.0-1.0>,
  "final_confidence": <0.0-1.0>,
  "position_size_usd": <number or 0 if HOLD>,
  "side": "YES" or "NO" or "NONE",
  "reasoning": "<2-3 sentence explanation of WHY this decision>",
  "agent_agreement": "unanimous" or "majority" or "split" or "override",
  "overrode_risk_agent": <true or false>
}

Rules:
- If Risk Agent blocked the trade, you should almost always HOLD (override only with extraordinary edge >20%)
- If Devil's Advocate found significant overconfidence, reduce confidence
- Apply DA's probability adjustment to the reasoning estimate
- Edge < 6% absolute -> HOLD regardless
- Confidence < 0.65 after adjustments -> HOLD
- If agents disagree strongly, prefer HOLD (uncertainty = no bet)
- NEVER override risk limits for a mediocre edge
- position_size_usd should be 0 for HOLD decisions"""

# Variable data — changes every call
USER_TEMPLATE = """## Market
Question: {question}
Market price: {market_price:.1%}
Days to resolution: {days_to_resolution}

## Agent 1 — Research Brief
Sentiment: {news_sentiment} | Quality: {info_quality}
Summary: {research_summary}

## Agent 2 — Reasoning (Superforecaster)
Probability: {reasoning_prob:.1%} (raw: {raw_prob:.1%}, calibrated)
Confidence: {reasoning_conf:.0%}
Key drivers: {key_drivers}
Assumptions: {assumptions}

## Agent 3 — Devil's Advocate
Overconfidence: {overconfidence}
Probability adjustment: {da_prob_adj:+.1%}
Confidence adjustment: {da_conf_adj:+.2f}
Strongest objection: {dissent}
High-severity challenges: {high_challenges}

## Agent 4 — Risk Assessment
Kelly direction: {kelly_direction} | Kelly size: ${kelly_usd:.2f} ({kelly_pct:.2%})
Correlation: {correlation_status} — {correlation_reason}
Portfolio: {deployed_pct:.0%} deployed, {position_count} open positions
Risk approved: {risk_approved}
{risk_block_reasons}"""


class DecisionAgent:
    """Agent 5: Final decision synthesizer."""

    def __init__(self):
        self.model = settings.DECISION_MODEL

    async def run(
        self,
        market: PolymarketMarket,
        research_brief: dict,
        reasoning_output: dict,
        da_output: dict,
        risk_output: dict,
    ) -> dict:
        kelly = risk_output.get("kelly", {})
        portfolio = risk_output.get("portfolio", {})
        correlation = risk_output.get("correlation", {})

        high_challenges = sum(
            1 for c in da_output.get("challenges", [])
            if c.get("severity") == "high"
        )

        block_reasons_str = ""
        if risk_output.get("block_reasons"):
            block_reasons_str = "BLOCKED: " + "; ".join(risk_output["block_reasons"])

        user_msg = USER_TEMPLATE.format(
            question=market.question,
            market_price=market.yes_price,
            days_to_resolution=market.days_to_resolution or "unknown",
            news_sentiment=research_brief.get("news_sentiment", "neutral"),
            info_quality=research_brief.get("information_quality", "low"),
            research_summary=research_brief.get("research_summary", "No research"),
            reasoning_prob=reasoning_output.get("calibrated_probability", 0.5),
            raw_prob=reasoning_output.get("raw_probability", 0.5),
            reasoning_conf=reasoning_output.get("confidence", 0.5),
            key_drivers="; ".join(reasoning_output.get("key_drivers", [])),
            assumptions="; ".join(reasoning_output.get("assumptions", [])),
            overconfidence=da_output.get("overconfidence_assessment", "unknown"),
            da_prob_adj=da_output.get("suggested_probability_adjustment", 0),
            da_conf_adj=da_output.get("suggested_confidence_adjustment", 0),
            dissent=da_output.get("dissent_summary", "No dissent"),
            high_challenges=high_challenges,
            kelly_direction=kelly.get("direction", "NONE"),
            kelly_usd=kelly.get("position_usd", 0),
            kelly_pct=kelly.get("position_pct", 0),
            correlation_status="CLEAR" if correlation.get("approved", True) else "BLOCKED",
            correlation_reason=correlation.get("reason", ""),
            deployed_pct=portfolio.get("deployed_pct", 0),
            position_count=portfolio.get("position_count", 0),
            risk_approved=risk_output.get("approved", False),
            risk_block_reasons=block_reasons_str,
        )

        try:
            data = call_llm_json(
                model=self.model,
                prompt=user_msg,
                system_prompt=SYSTEM_PROMPT,
                max_tokens=800,
                temperature=0.2,
            )

            decision_str = data.get("decision", "HOLD")
            try:
                signal = SignalStrength(decision_str)
            except ValueError:
                signal = SignalStrength.HOLD

            result = {
                "agent": "decision",
                "signal": signal,
                "final_probability": float(data.get("final_probability", 0.5)),
                "final_confidence": float(data.get("final_confidence", 0.5)),
                "position_size_usd": float(data.get("position_size_usd", 0)),
                "side": data.get("side", "NONE"),
                "reasoning": data.get("reasoning", ""),
                "agent_agreement": data.get("agent_agreement", "unknown"),
                "overrode_risk_agent": data.get("overrode_risk_agent", False),
            }

            logger.info(
                f"Decision Agent: {market.question[:50]} | "
                f"{signal.value} | P={result['final_probability']:.1%} | "
                f"Conf={result['final_confidence']:.0%} | "
                f"${result['position_size_usd']:.0f} {result['side']} | "
                f"agreement={result['agent_agreement']}"
            )
            return result

        except Exception as e:
            logger.error(f"Decision Agent failed for '{market.question[:50]}': {e}")
            return {
                "agent": "decision",
                "signal": SignalStrength.HOLD,
                "final_probability": reasoning_output.get("calibrated_probability", 0.5),
                "final_confidence": 0.0,
                "position_size_usd": 0,
                "side": "NONE",
                "reasoning": f"Decision agent failed: {e}. Defaulting to HOLD.",
                "agent_agreement": "error",
                "overrode_risk_agent": False,
            }
