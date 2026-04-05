"""
agents/devils_advocate.py
AGENT 3: Devil's Advocate Agent (DeepSeek R1)

Challenges the Reasoning Agent's conclusions. Looks for blind spots,
overconfidence, and unconsidered scenarios. May adjust the probability.
"""

from loguru import logger

from agents.base import call_llm_json
from core.models import PolymarketMarket
from config.settings import settings


DEVILS_ADVOCATE_PROMPT = """You are a Devil's Advocate analyst whose job is to CHALLENGE a forecaster's probability estimate.
Your goal: find blind spots, overconfidence, and unconsidered scenarios.

## Market
Question: {question}
Market price: {market_price:.1%}
Days until resolution: {days_to_resolution}

## Forecaster's Output
Probability estimate: {our_probability:.1%}
Confidence: {confidence:.0%}
Key drivers: {key_drivers}
Assumptions: {assumptions}
Reasoning steps summary: {reasoning_summary}

## Research Brief
News sentiment: {news_sentiment}
Information quality: {info_quality}
Key uncertainties: {uncertainties}

## Your Task
Aggressively challenge this estimate. Consider:
1. What if the key assumptions are WRONG?
2. What scenarios has the forecaster NOT considered?
3. Is the confidence level justified by the evidence quality?
4. Are there tail risks or black swan events being ignored?
5. Is the forecaster anchoring too much to the base rate or news?
6. Could resolution criteria be ambiguous?

Respond ONLY with valid JSON:
{{
  "challenges": [
    {{"challenge": "<specific challenge>", "severity": "high" or "medium" or "low", "impact_on_probability": <-0.3 to +0.3>}},
    ...
  ],
  "blind_spots": ["<unconsidered factor 1>", ...],
  "overconfidence_assessment": "justified" or "slightly_overconfident" or "significantly_overconfident" or "underconfident",
  "suggested_confidence_adjustment": <-0.3 to +0.1>,
  "suggested_probability_adjustment": <-0.2 to +0.2>,
  "worst_case_scenario": "<what could make this estimate completely wrong?>",
  "dissent_summary": "<1-2 sentence summary of your strongest objection>"
}}

Rules:
- Be genuinely adversarial — don't rubber-stamp the estimate
- At least ONE challenge must be severity "high"
- If info quality is "low", overconfidence assessment should be "slightly" or "significantly" overconfident
- Probability adjustments should be proportional to evidence strength
- If the estimate seems well-reasoned, say so but still find challenges"""


class DevilsAdvocateAgent:
    """
    Agent 3: Challenges the reasoning agent's conclusions.
    Uses DeepSeek R1 for deep adversarial reasoning.
    """

    def __init__(self):
        self.model = settings.DEVILS_ADVOCATE_MODEL

    async def run(
        self,
        market: PolymarketMarket,
        reasoning_output: dict,
        research_brief: dict,
    ) -> dict:
        """
        Run the Devil's Advocate Agent.
        Returns challenges and suggested adjustments.
        """
        # Summarize reasoning steps
        steps = reasoning_output.get("steps", [])
        reasoning_summary = "; ".join(
            f"{s.get('step', 'unknown')}: {s.get('analysis', '')[:100]}"
            for s in steps[:4]
        )

        prompt = DEVILS_ADVOCATE_PROMPT.format(
            question=market.question,
            market_price=market.yes_price,
            days_to_resolution=market.days_to_resolution or "unknown",
            our_probability=reasoning_output.get("calibrated_probability", 0.5),
            confidence=reasoning_output.get("confidence", 0.5),
            key_drivers="; ".join(reasoning_output.get("key_drivers", [])),
            assumptions="; ".join(reasoning_output.get("assumptions", [])),
            reasoning_summary=reasoning_summary,
            news_sentiment=research_brief.get("news_sentiment", "neutral"),
            info_quality=research_brief.get("information_quality", "low"),
            uncertainties="; ".join(research_brief.get("key_uncertainties", [])),
        )

        try:
            data = call_llm_json(
                model=self.model,
                prompt=prompt,
                max_tokens=1500,
                temperature=0.4,
            )

            result = {
                "agent": "devils_advocate",
                "challenges": data.get("challenges", []),
                "blind_spots": data.get("blind_spots", []),
                "overconfidence_assessment": data.get("overconfidence_assessment", "justified"),
                "suggested_confidence_adjustment": float(data.get("suggested_confidence_adjustment", 0)),
                "suggested_probability_adjustment": float(data.get("suggested_probability_adjustment", 0)),
                "worst_case_scenario": data.get("worst_case_scenario", ""),
                "dissent_summary": data.get("dissent_summary", ""),
            }

            # Count high-severity challenges
            high_challenges = sum(
                1 for c in result["challenges"]
                if c.get("severity") == "high"
            )

            logger.debug(
                f"Devil's Advocate: {market.question[:50]} | "
                f"{len(result['challenges'])} challenges ({high_challenges} high) | "
                f"overconf={result['overconfidence_assessment']} | "
                f"prob_adj={result['suggested_probability_adjustment']:+.1%}"
            )
            return result

        except Exception as e:
            logger.error(f"Devil's Advocate failed for '{market.question[:50]}': {e}")
            # Conservative fallback: flag as potentially overconfident
            return {
                "agent": "devils_advocate",
                "challenges": [{"challenge": "DA agent failed - treat with extra caution", "severity": "high", "impact_on_probability": 0}],
                "blind_spots": ["Devil's advocate analysis unavailable"],
                "overconfidence_assessment": "slightly_overconfident",
                "suggested_confidence_adjustment": -0.1,
                "suggested_probability_adjustment": 0.0,
                "worst_case_scenario": "Unknown — DA analysis failed",
                "dissent_summary": "Could not challenge estimate. Reduce confidence as precaution.",
            }
