"""
data/news_fetcher.py
Fetches real-time news relevant to a specific market.
This feeds the reasoning engine with current information —
the core advantage over bots that only look at price data.
"""

import httpx
import feedparser
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from core.models import PolymarketMarket, NewsItem


# News RSS sources for each domain
DOMAIN_RSS_FEEDS = {
    "crypto": [
        "https://feeds.bloomberg.com/crypto/news.rss",
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
        "https://theblock.co/rss.xml",
    ],
    "politics": [
        "https://feeds.reuters.com/reuters/politicsNews",
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
        "https://feeds.bbci.co.uk/news/politics/rss.xml",
        "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",  # Indian politics
    ],
    "economics": [
        "https://feeds.bloomberg.com/economics/news.rss",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://rbi.org.in/scripts/rss.aspx",  # RBI press releases
    ],
}

# Google News search URL (no API key needed)
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"


class NewsFetcher:
    """
    Fetches recent news relevant to a Polymarket market.
    Uses RSS feeds + Google News for real-time context.
    """

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "PolymarketResearchBot/1.0"}
        )
        self._cache: dict = {}  # Simple in-memory cache
        self._cache_ttl_minutes = 10

    def _extract_keywords(self, market: PolymarketMarket) -> List[str]:
        """Extract search keywords from a market question."""
        question = market.question.lower()

        # Remove common prediction market filler words
        stopwords = {
            "will", "the", "a", "an", "in", "on", "at", "by", "for",
            "to", "of", "is", "be", "before", "after", "when", "does",
            "happen", "occur", "reach", "hit", "above", "below", "end",
            "year", "month", "quarter", "week", "day", "2024", "2025", "2026"
        }

        words = question.split()
        keywords = [w.strip("?,.'\"") for w in words if w not in stopwords and len(w) > 3]

        # Take top 4 most distinctive keywords
        return keywords[:4]

    async def _fetch_rss(self, url: str) -> List[dict]:
        """Fetch and parse an RSS feed, returning list of entries."""
        cache_key = f"rss:{url}"
        cached = self._cache.get(cache_key)
        if cached and (datetime.utcnow() - cached["fetched"]).seconds < self._cache_ttl_minutes * 60:
            return cached["data"]

        try:
            resp = await self.client.get(url)
            feed = feedparser.parse(resp.text)
            entries = []
            for entry in feed.entries[:20]:  # Max 20 per feed
                entries.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": feed.feed.get("title", url),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:500],
                })
            self._cache[cache_key] = {"data": entries, "fetched": datetime.utcnow()}
            return entries
        except Exception as e:
            logger.debug(f"RSS fetch failed for {url}: {e}")
            return []

    async def _fetch_google_news(self, keywords: List[str]) -> List[dict]:
        """Fetch Google News RSS for specific keywords."""
        query = "+".join(keywords)
        url = GOOGLE_NEWS_RSS.format(query=query)
        return await self._fetch_rss(url)

    def _score_relevance(self, item: dict, market: PolymarketMarket) -> float:
        """
        Score how relevant a news item is to the market.
        Returns 0.0–1.0.
        """
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        question_words = set(market.question.lower().split())
        keywords = self._extract_keywords(market)

        score = 0.0
        # Keyword hits
        for kw in keywords:
            if kw.lower() in text:
                score += 0.2
        # Recency bonus (prefer last 24h)
        pub_str = item.get("published", "")
        if pub_str:
            try:
                # Simple heuristic: if "hour" in published string, it's recent
                if "hour" in pub_str or "minute" in pub_str:
                    score += 0.2
                elif "day" in pub_str:
                    score += 0.1
            except Exception:
                pass

        return min(1.0, score)

    async def fetch_for_market(
        self,
        market: PolymarketMarket,
        max_items: int = 8
    ) -> List[NewsItem]:
        """
        Fetch and rank news items relevant to a specific market.
        Combines domain RSS feeds + targeted Google News search.
        """
        domain_str = market.domain.value
        keywords = self._extract_keywords(market)

        # Fetch from domain-specific RSS + Google News in parallel
        tasks = []

        # Domain RSS feeds
        for feed_url in DOMAIN_RSS_FEEDS.get(domain_str, []):
            tasks.append(self._fetch_rss(feed_url))

        # Google News targeted search
        if keywords:
            tasks.append(self._fetch_google_news(keywords))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        for result in results:
            if isinstance(result, list):
                all_items.extend(result)

        # Score and filter
        scored = []
        seen_urls = set()
        for item in all_items:
            url = item.get("url", "")
            if url in seen_urls or not url:
                continue
            seen_urls.add(url)

            relevance = self._score_relevance(item, market)
            if relevance > 0.1:  # Minimum relevance threshold
                scored.append((relevance, item))

        # Sort by relevance descending
        scored.sort(key=lambda x: x[0], reverse=True)

        news_items = []
        for relevance, item in scored[:max_items]:
            news_items.append(NewsItem(
                title=item.get("title", ""),
                url=item.get("url", ""),
                source=item.get("source", ""),
                summary=item.get("summary", ""),
                relevance_score=relevance,
            ))

        logger.debug(
            f"News for '{market.question[:50]}...': "
            f"{len(news_items)} relevant items (from {len(all_items)} total)"
        )
        return news_items

    async def close(self):
        await self.client.aclose()
