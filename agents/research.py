"""
agents/research.py
AGENT 1: Research Agent (DeepSeek V3)

Synthesizes news, cross-platform prices, and market context into
a structured research brief for the Reasoning Agent.

Prompt split for prefix caching:
  SYSTEM_PROMPT (static, cached) — role + output format + rules
  USER_TEMPLATE (variable) — market data + news + cross-platform
"""

from typing import List, Optional
from loguru import logger

from agents.base import call_llm_json
from core.models import PolymarketMarket, NewsItem
from config.settings import settings


# Static instructions — CACHED by DeepSeek across all calls
SYSTEM_PROMPT = """You are a research analyst preparing a brief for a prediction market forecaster.
Synthesize all available information into a structured research report.

Respond ONLY with valid JSON:
{
  "key_facts": ["<fact 1>", "<fact 2>", ...],
  "bullish_factors": ["<factor pushing YES higher>", ...],
  "bearish_factors": ["<factor pushing YES lower>", ...],
  "information_quality": "high" or "medium" or "low",
  "recency_score": 0.0-1.0,
  "news_sentiment": "strongly_bullish" or "bullish" or "neutral" or "bearish" or "strongly_bearish",
  "cross_platform_consensus": "<what other platforms suggest, or 'no data'>",
  "key_uncertainties": ["<uncertainty 1>", "<uncertainty 2>"],
  "research_summary": "<2-3 sentence synthesis of all evidence>"
}

Rules:
- Focus on FACTS, not opinions
- Flag conflicting information explicitly
- Rate information quality honestly (low if mostly stale/irrelevant news)
- Recency score: 1.0 = breaking news today, 0.5 = news this week, 0.0 = no recent news
- If news is scarce, say so clearly — don't fabricate context"""

# Variable data — changes every call
USER_TEMPLATE = """## Market
Question: {question}
Description: {description}
Domain: {domain}
Days until resolution: {days_to_resolution}
Resolution source: {resolution_source}
Current market price (YES): {market_price:.1%}

## News Articles
{news_context}

## Cross-Platform Prices
{cross_platform_context}"""


class ResearchAgent:
    """Agent 1: Gathers and synthesizes all available information."""

    def __init__(self):
        self.model = settings.RESEARCH_MODEL

    def _format_news(self, news_items: List[NewsItem]) -> str:
        if not news_items:
            return "No recent news found."
        lines = []
        for i, item in enumerate(news_items[:8]):
            age = ""
            if item.published_at:
                from datetime import datetime
                hours = (datetime.utcnow() - item.published_at).total_seconds() / 3600
                if hours < 24:
                    age = f" [{int(hours)}h ago]"
                elif hours < 168:
                    age = f" [{int(hours/24)}d ago]"
                else:
                    age = " [>1 week old]"
            lines.append(
                f"[{i+1}] {item.source}{age}\n"
                f"    Title: {item.title}\n"
                f"    {(item.summary or 'No summary')[:250]}"
            )
        return "\n\n".join(lines)

    async def run(
        self,
        market: PolymarketMarket,
        news_items: List[NewsItem],
        cross_platform_context: str = "",
    ) -> dict:
        news_context = self._format_news(news_items)

        user_msg = USER_TEMPLATE.format(
            question=market.question,
            description=(market.description or "")[:400],
            domain=market.domain.value,
            days_to_resolution=market.days_to_resolution or "unknown",
            resolution_source=market.resolution_source or "unspecified",
            market_price=market.yes_price,
            news_context=news_context,
            cross_platform_context=cross_platform_context or "No cross-platform data available.",
        )

        try:
            result = call_llm_json(
                model=self.model,
                prompt=user_msg,
                system_prompt=SYSTEM_PROMPT,
                max_tokens=1000,
                temperature=0.2,
            )
            result["agent"] = "research"
            result["market_question"] = market.question
            logger.debug(
                f"Research Agent: {market.question[:50]} | "
                f"sentiment={result.get('news_sentiment', 'unknown')} | "
                f"quality={result.get('information_quality', 'unknown')}"
            )
            return result

        except Exception as e:
            logger.error(f"Research Agent failed for '{market.question[:50]}': {e}")
            return {
                "agent": "research",
                "market_question": market.question,
                "key_facts": [],
                "bullish_factors": [],
                "bearish_factors": [],
                "information_quality": "low",
                "recency_score": 0.0,
                "news_sentiment": "neutral",
                "cross_platform_consensus": "no data",
                "key_uncertainties": ["Research agent failed - proceed with caution"],
                "research_summary": "Research unavailable. Rely on base rates only.",
            }
