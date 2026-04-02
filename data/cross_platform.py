"""
data/cross_platform.py
Fetches comparable market prices from Metaculus and Kalshi APIs.
Passes price discrepancies as context to the reasoning engine.
"""

import httpx
import asyncio
import re
from typing import Optional, List, Dict
from loguru import logger


class CrossPlatformFetcher:
    """Pulls comparable prediction market prices from Metaculus and Kalshi."""

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "PolymarketResearchBot/1.0"},
            follow_redirects=True,
        )

    # ── Metaculus ─────────────────────────────────────────────────────────

    async def search_metaculus(self, query: str) -> Optional[Dict]:
        """Search Metaculus for a comparable question and return its community prediction."""
        try:
            # Metaculus API: search questions
            resp = await self._client.get(
                "https://www.metaculus.com/api2/questions/",
                params={
                    "search": query[:80],
                    "status": "open",
                    "type": "binary",
                    "limit": 5,
                    "order_by": "-activity",
                },
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None

            # Find best match by keyword overlap
            query_words = set(re.findall(r'\w+', query.lower()))
            best = None
            best_score = 0
            for q in results:
                title = q.get("title", "")
                title_words = set(re.findall(r'\w+', title.lower()))
                overlap = len(query_words & title_words)
                if overlap > best_score:
                    best_score = overlap
                    best = q

            if not best or best_score < 3:
                return None

            # Extract community prediction
            prediction = best.get("community_prediction", {})
            full = prediction.get("full", {})
            q2 = full.get("q2")  # Median prediction

            if q2 is None:
                return None

            return {
                "platform": "Metaculus",
                "question": best.get("title", ""),
                "url": f"https://www.metaculus.com/questions/{best.get('id')}/",
                "probability": round(q2, 4),
                "forecasters": best.get("number_of_predictions", 0),
                "match_score": best_score,
            }

        except Exception as e:
            logger.debug(f"Metaculus search failed: {e}")
            return None

    # ── Kalshi ────────────────────────────────────────────────────────────

    async def search_kalshi(self, query: str) -> Optional[Dict]:
        """Search Kalshi for a comparable event and return its market price."""
        try:
            resp = await self._client.get(
                "https://api.elections.kalshi.com/trade-api/v2/markets",
                params={
                    "status": "open",
                    "limit": 10,
                },
            )
            if resp.status_code != 200:
                # Try the demo/public API
                resp = await self._client.get(
                    "https://demo-api.kalshi.co/trade-api/v2/markets",
                    params={"status": "open", "limit": 20},
                )
                if resp.status_code != 200:
                    return None

            data = resp.json()
            markets = data.get("markets", [])
            if not markets:
                return None

            query_words = set(re.findall(r'\w+', query.lower()))
            best = None
            best_score = 0
            for m in markets:
                title = m.get("title", "") + " " + m.get("subtitle", "")
                title_words = set(re.findall(r'\w+', title.lower()))
                overlap = len(query_words & title_words)
                if overlap > best_score:
                    best_score = overlap
                    best = m

            if not best or best_score < 3:
                return None

            yes_price = best.get("yes_bid", 0) or best.get("last_price", 0)
            if yes_price and yes_price > 1:
                yes_price = yes_price / 100.0  # Kalshi uses cents

            return {
                "platform": "Kalshi",
                "question": best.get("title", ""),
                "ticker": best.get("ticker", ""),
                "probability": round(yes_price, 4) if yes_price else None,
                "volume": best.get("volume", 0),
                "match_score": best_score,
            }

        except Exception as e:
            logger.debug(f"Kalshi search failed: {e}")
            return None

    # ── Combined ──────────────────────────────────────────────────────────

    async def get_cross_platform_prices(self, market_question: str) -> Dict:
        """
        Fetch prices from Metaculus and Kalshi for a given market question.
        Returns a dict with platform prices and discrepancy analysis.
        """
        # Simplify query: take first 60 chars, remove common filler
        query = re.sub(r'\b(will|the|be|by|in|on|of|a|an|to)\b', '', market_question, flags=re.I)
        query = re.sub(r'\s+', ' ', query).strip()[:80]

        metaculus, kalshi = await asyncio.gather(
            self.search_metaculus(query),
            self.search_kalshi(query),
            return_exceptions=True,
        )

        if isinstance(metaculus, Exception):
            metaculus = None
        if isinstance(kalshi, Exception):
            kalshi = None

        result = {
            "metaculus": metaculus,
            "kalshi": kalshi,
            "has_cross_platform": bool(metaculus or kalshi),
        }

        # Calculate discrepancies if we have data
        platforms_with_prices = []
        if metaculus and metaculus.get("probability"):
            platforms_with_prices.append(("Metaculus", metaculus["probability"]))
        if kalshi and kalshi.get("probability"):
            platforms_with_prices.append(("Kalshi", kalshi["probability"]))

        result["platforms_found"] = len(platforms_with_prices)
        result["prices"] = platforms_with_prices

        return result

    def format_for_prompt(self, cross_data: Dict, polymarket_price: float) -> str:
        """Format cross-platform data as context string for Claude."""
        if not cross_data.get("has_cross_platform"):
            return ""

        lines = ["\n## Cross-Platform Price Comparison"]
        lines.append(f"Polymarket YES price: {polymarket_price:.1%}")

        for platform, price in cross_data.get("prices", []):
            diff = price - polymarket_price
            direction = "higher" if diff > 0 else "lower"
            lines.append(
                f"{platform}: {price:.1%} ({abs(diff):.1%} {direction} than Polymarket)"
            )

        # Flag significant discrepancies
        for platform, price in cross_data.get("prices", []):
            diff = abs(price - polymarket_price)
            if diff >= 0.10:
                lines.append(
                    f"SIGNIFICANT DISCREPANCY: {platform} differs by {diff:.1%} — "
                    f"investigate whether Polymarket is mispriced or {platform} has different information."
                )

        return "\n".join(lines)

    def serialize(self, cross_data: Dict) -> str:
        """Serialize cross-platform data for DB storage."""
        import json
        serializable = {}
        for key in ["metaculus", "kalshi", "platforms_found"]:
            serializable[key] = cross_data.get(key)
        return json.dumps(serializable, default=str)

    async def close(self):
        await self._client.aclose()
