"""
core/market_fetcher.py
Fetches and filters markets from Polymarket's Gamma API.
Phase 1: Read-only. No authentication required.
"""

import httpx
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from core.models import PolymarketMarket, OutcomeToken, Domain
from config.settings import settings


class MarketFetcher:
    """
    Pulls active markets from Polymarket Gamma API.
    Filters by domain, liquidity, volume, and time-to-resolution.
    """

    def __init__(self):
        self.base_url = settings.GAMMA_API_URL
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "PolymarketResearchBot/1.0 (Phase1-PaperOnly)"}
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def fetch_active_markets(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Fetch raw active markets from Gamma API with pagination."""
        params = {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "limit": limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }
        try:
            resp = await self.client.get(f"{self.base_url}/markets", params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Gamma API error {e.response.status_code}: {e}")
            raise
        except Exception as e:
            logger.error(f"Market fetch error: {e}")
            raise

    async def fetch_all_active_markets(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Paginate through active markets (capped at max_pages to avoid timeouts)."""
        all_markets = []
        offset = 0
        limit = 100

        for page in range(max_pages):
            batch = await self.fetch_active_markets(limit=limit, offset=offset)
            if not batch:
                break
            all_markets.extend(batch)
            logger.debug(f"Fetched {len(all_markets)} markets so far (page {page + 1}/{max_pages})...")
            if len(batch) < limit:
                break
            offset += limit
            await asyncio.sleep(0.5)  # Respectful rate limiting

        logger.info(f"Total raw markets fetched: {len(all_markets)}")
        return all_markets

    def _classify_domain(self, market: Dict[str, Any]) -> Domain:
        """Classify a market into one of our focus domains using word boundary matching."""
        import re
        text = (
            (market.get("question") or "") + " " +
            (market.get("description") or "") + " " +
            (market.get("category") or "") + " " +
            " ".join(market.get("tags") or [])
        ).lower()

        for domain_name, keywords in settings.DOMAIN_KEYWORDS.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', text) for kw in keywords):
                return Domain(domain_name)

        return Domain.OTHER

    def _parse_tokens(self, market: Dict[str, Any]) -> List[OutcomeToken]:
        """Parse YES/NO token prices from raw market data."""
        import json as _json
        tokens = []

        # Gamma API returns outcomes, outcomePrices, clobTokenIds as JSON strings
        raw_outcomes = market.get("outcomes") or "[]"
        raw_prices = market.get("outcomePrices") or "[]"
        raw_token_ids = market.get("clobTokenIds") or "[]"

        if isinstance(raw_outcomes, str):
            try:
                raw_outcomes = _json.loads(raw_outcomes)
            except (ValueError, TypeError):
                raw_outcomes = []
        if isinstance(raw_prices, str):
            try:
                raw_prices = _json.loads(raw_prices)
            except (ValueError, TypeError):
                raw_prices = []
        if isinstance(raw_token_ids, str):
            try:
                raw_token_ids = _json.loads(raw_token_ids)
            except (ValueError, TypeError):
                raw_token_ids = []

        for i, outcome in enumerate(raw_outcomes):
            try:
                price = float(raw_prices[i]) if i < len(raw_prices) else 0.5
                token_id = str(raw_token_ids[i]) if i < len(raw_token_ids) else ""
                tokens.append(OutcomeToken(
                    token_id=token_id,
                    outcome=str(outcome),
                    price=max(0.001, min(0.999, price)),
                ))
            except Exception as e:
                logger.debug(f"Token parse error: {e}")

        return tokens

    def _days_to_resolution(self, market: Dict[str, Any]) -> Optional[int]:
        """Calculate days until market resolution."""
        end_str = market.get("endDate") or market.get("end_date_iso") or ""
        if not end_str:
            return None
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = (end - now).days
            return max(0, delta)
        except Exception:
            return None

    def _parse_market(self, raw: Dict[str, Any]) -> Optional[PolymarketMarket]:
        """Parse a raw API response into a PolymarketMarket model."""
        try:
            tokens = self._parse_tokens(raw)

            # Extract YES price
            yes_price = 0.5
            no_price = 0.5
            for tok in tokens:
                if tok.outcome.lower() in ("yes", "1"):
                    yes_price = tok.price
                elif tok.outcome.lower() in ("no", "0"):
                    no_price = tok.price

            # Fallback: if only one token, infer the other
            if yes_price == 0.5 and no_price != 0.5:
                yes_price = 1.0 - no_price
            if no_price == 0.5 and yes_price != 0.5:
                no_price = 1.0 - yes_price

            days_to_res = self._days_to_resolution(raw)

            market = PolymarketMarket(
                condition_id=raw.get("conditionId") or raw.get("condition_id") or "",
                question=raw.get("question") or raw.get("title") or "",
                description=raw.get("description") or "",
                category=raw.get("category") or "",
                domain=self._classify_domain(raw),
                tokens=tokens,
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=float(raw.get("volume24hr") or raw.get("volume_24hr") or 0),
                liquidity=float(raw.get("liquidity") or 0),
                total_volume=float(raw.get("volume") or 0),
                days_to_resolution=days_to_res,
                resolution_source=raw.get("resolutionSource") or raw.get("resolution_source") or "",
                active=raw.get("active", True),
                closed=raw.get("closed", False),
                tags=raw.get("tags") or [],
                market_slug=raw.get("market_slug") or raw.get("slug") or "",
            )
            return market
        except Exception as e:
            logger.debug(f"Market parse failed for '{raw.get('question', 'unknown')}': {e}")
            return None

    def filter_markets(self, markets: List[PolymarketMarket]) -> List[PolymarketMarket]:
        """
        Apply all filters: domain, liquidity, volume, timing, probability band.
        This is where we enforce our domain specialisation strategy.
        """
        filtered = []
        stats = {"total": len(markets), "domain": 0, "liquidity": 0,
                 "volume": 0, "timing": 0, "prob_band": 0, "passed": 0}

        for m in markets:
            # 1. Domain filter — ONLY our focus areas
            if m.domain not in [Domain(d) for d in settings.FOCUS_DOMAINS]:
                stats["domain"] += 1
                continue

            # 2. Liquidity filter
            if m.liquidity < settings.MIN_LIQUIDITY_USD:
                stats["liquidity"] += 1
                continue

            # 3. Volume filter
            if m.volume_24h < settings.MIN_VOLUME_24H:
                stats["volume"] += 1
                continue

            # 4. Timing filter
            if m.days_to_resolution is not None:
                if m.days_to_resolution < settings.MIN_DAYS_TO_RESOLUTION:
                    stats["timing"] += 1
                    continue
                if m.days_to_resolution > settings.MAX_DAYS_TO_RESOLUTION:
                    stats["timing"] += 1
                    continue

            # 5. Probability band filter (avoid near-certainties)
            if not (settings.PROBABILITY_BAND_MIN <= m.yes_price <= settings.PROBABILITY_BAND_MAX):
                stats["prob_band"] += 1
                continue

            filtered.append(m)
            stats["passed"] += 1

        logger.info(
            f"Market filter: {stats['total']} total -> "
            f"{stats['domain']} domain-rejected, "
            f"{stats['liquidity']} illiquid, "
            f"{stats['volume']} low-volume, "
            f"{stats['timing']} bad-timing, "
            f"{stats['prob_band']} out-of-band -> "
            f"{stats['passed']} passed"
        )
        return filtered

    async def get_qualified_markets(self) -> List[PolymarketMarket]:
        """Full pipeline: fetch -> parse -> filter -> return qualified markets."""
        raw_markets = await self.fetch_all_active_markets()
        parsed = [m for raw in raw_markets if (m := self._parse_market(raw)) is not None]
        qualified = self.filter_markets(parsed)
        logger.info(f"Qualified markets for reasoning: {len(qualified)}")
        return qualified

    async def close(self):
        await self.client.aclose()
