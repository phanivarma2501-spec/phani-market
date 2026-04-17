import requests
import json
from typing import Dict
from settings import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, RESEARCH_MODEL
from data.gdelt import get_news_context
from data.metaculus import search_metaculus


def research_market(market: Dict) -> Dict:
    """
    Research a market using GDELT news + Metaculus comparison.
    Returns enriched market dict with news context and metaculus probability.
    """
    question = market["question"]

    # 1. Fetch GDELT news context
    print(f"  [Research] Fetching news for: {question[:60]}...")
    news_context = get_news_context(question)

    # 2. Metaculus (currently disabled — returns None)
    metaculus_prob = search_metaculus(question)
    if metaculus_prob is not None:
        print(f"  [Research] Metaculus probability: {metaculus_prob:.1%}")

    # 3. Summarise with DeepSeek V3
    summary = _summarise_context(question, news_context, metaculus_prob)

    return {
        **market,
        "news_context": news_context,
        "metaculus_probability": metaculus_prob,
        "research_summary": summary,
    }


def _summarise_context(question: str, news: str, metaculus_prob: float) -> str:
    """Use DeepSeek V3 to summarise research context."""
    metaculus_str = f"{metaculus_prob:.1%}" if metaculus_prob is not None else "Not available"

    prompt = f"""You are a research analyst for a prediction market trading bot.

Market Question: {question}

Recent News:
{news}

Metaculus Community Forecast: {metaculus_str}

Provide a concise 3-5 sentence research summary covering:
1. What the current evidence suggests about this outcome
2. Key factors that could push this YES or NO
3. Any notable uncertainty or upcoming events

Be factual and objective. Do not give a probability estimate here."""

    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": RESEARCH_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [Research] Summarisation error: {e}")
        return f"News context: {news[:200]}"
