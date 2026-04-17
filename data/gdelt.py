import requests
from typing import List, Dict
from settings import GDELT_BASE_URL


def get_news_context(question: str, max_articles: int = 5) -> str:
    """
    Fetch recent news articles from GDELT relevant to the market question.
    Returns a summarised string of headlines and snippets.
    """
    try:
        keywords = _extract_search_query(question)
        params = {
            "query": keywords,
            "mode": "artlist",
            "maxrecords": max_articles,
            "timespan": "3d",   # Last 3 days
            "sort": "DateDesc",
            "format": "json",
        }
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])

        if not articles:
            return "No recent news found."

        summaries = []
        for a in articles:
            title = a.get("title", "")
            url = a.get("url", "")
            seendate = a.get("seendate", "")[:8] if a.get("seendate") else ""
            if title:
                summaries.append(f"- [{seendate}] {title} ({url})")

        return "\n".join(summaries) if summaries else "No recent news found."

    except Exception as e:
        print(f"[GDELT] Error fetching news: {e}")
        return "News fetch failed."


def _extract_search_query(question: str) -> str:
    """Convert market question to GDELT search query."""
    # Remove question marks and common filler
    stop_words = {"will", "the", "a", "an", "be", "in", "by", "to", "of",
                  "and", "or", "is", "are", "was", "were", "has", "have",
                  "that", "this", "for", "with", "at", "from", "before",
                  "after", "during", "between", "who", "what", "when",
                  "where", "which", "how", "do", "does", "did"}
    words = question.lower().replace("?", "").replace(",", "").split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    # Take top 5 keywords and join with AND
    top = keywords[:5]
    return " ".join(top)
