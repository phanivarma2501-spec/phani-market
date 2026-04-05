"""
core/discovery.py
Market Discovery System — replaces manual watchlist with automatic discovery.

Flow:
  1. Fetch ALL active Polymarket markets (paginated)
  2. Apply hard filters (volume, liquidity, timing, probability band)
  3. Score each market by opportunity signals (price movement, volume trend, etc.)
  4. Priority queue: rank by opportunity score
  5. Pass top N markets to the 5-agent pipeline

Runs on two cycles:
  - Full discovery: every 60 min (fetches all markets, rescores everything)
  - Quick rescore: every 15 min (rescores active positions + top candidates)
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from loguru import logger

from core.market_fetcher import MarketFetcher
from core.models import PolymarketMarket, Domain
from config.settings import settings


class OpportunityScorer:
    """
    Rule-based opportunity pre-filter. No LLM, pure math.
    Scores each market on multiple signals to find the best opportunities.
    """

    def score(self, market: PolymarketMarket, price_history: Dict = None) -> Dict:
        """
        Score a market's opportunity quality. Returns dict with component scores
        and total_score (0-100). Higher = better opportunity.
        """
        scores = {}

        # 1. Price movement score (0-25): larger recent movement = more opportunity
        price_move = self._price_movement_score(market, price_history)
        scores["price_movement"] = price_move

        # 2. Volume score (0-25): higher volume = more liquid opportunity
        scores["volume"] = self._volume_score(market)

        # 3. Time urgency score (0-25): closer to resolution = higher priority
        scores["time_urgency"] = self._time_urgency_score(market)

        # 4. Liquidity depth score (0-15): more liquidity = easier to trade
        scores["liquidity"] = self._liquidity_score(market)

        # 5. Mispricing signal (0-10): price far from 50% = potential edge
        scores["mispricing"] = self._mispricing_score(market)

        total = sum(scores.values())
        scores["total_score"] = round(total, 1)
        return scores

    def _price_movement_score(self, market: PolymarketMarket, history: Dict = None) -> float:
        """Score based on recent price movement. >5% in 24h = high score."""
        # If we have price history, use it
        if history and history.get("price_24h_ago"):
            price_now = market.yes_price
            price_24h = history["price_24h_ago"]
            move_pct = abs(price_now - price_24h) / max(price_24h, 0.01)
            if move_pct >= 0.15:
                return 25.0
            elif move_pct >= 0.10:
                return 20.0
            elif move_pct >= 0.05:
                return 15.0
            elif move_pct >= 0.03:
                return 8.0
            return 3.0

        # Without history, score based on how far price is from a round number
        # (proxy: extreme prices suggest recent movement)
        price = market.yes_price
        dist_from_50 = abs(price - 0.5)
        if dist_from_50 > 0.3:
            return 10.0  # Very far from 50%, something happened
        elif dist_from_50 > 0.2:
            return 7.0
        return 3.0

    def _volume_score(self, market: PolymarketMarket) -> float:
        """Higher 24h volume = more interest = better opportunity."""
        vol = market.volume_24h
        if vol >= 100_000:
            return 25.0
        elif vol >= 50_000:
            return 20.0
        elif vol >= 20_000:
            return 15.0
        elif vol >= 10_000:
            return 10.0
        elif vol >= 5_000:
            return 5.0
        return 2.0

    def _time_urgency_score(self, market: PolymarketMarket) -> float:
        """Closer to resolution = higher priority (more actionable)."""
        days = market.days_to_resolution
        if days is None:
            return 5.0
        if days <= 3:
            return 25.0
        elif days <= 7:
            return 20.0
        elif days <= 14:
            return 15.0
        elif days <= 21:
            return 10.0
        elif days <= 30:
            return 7.0
        return 3.0

    def _liquidity_score(self, market: PolymarketMarket) -> float:
        """More liquidity = easier to enter/exit."""
        liq = market.liquidity
        if liq >= 100_000:
            return 15.0
        elif liq >= 50_000:
            return 12.0
        elif liq >= 20_000:
            return 9.0
        elif liq >= 10_000:
            return 6.0
        return 3.0

    def _mispricing_score(self, market: PolymarketMarket) -> float:
        """
        Markets near 15-40% or 60-85% are more likely mispriced than
        those near 50% (uncertain) or near 0/100% (certain).
        """
        p = market.yes_price
        # Sweet spots: 20-35% and 65-80% — confident enough to bet, uncertain enough to be wrong
        if 0.20 <= p <= 0.35 or 0.65 <= p <= 0.80:
            return 10.0
        elif 0.15 <= p <= 0.40 or 0.60 <= p <= 0.85:
            return 7.0
        elif 0.40 <= p <= 0.60:
            return 4.0
        return 2.0


class MarketDiscovery:
    """
    Automatic market discovery system.
    Replaces manual watchlist with paginated API scan + opportunity scoring.
    """

    def __init__(self):
        self.fetcher = MarketFetcher()
        self.scorer = OpportunityScorer()
        self._market_cache: Dict[str, PolymarketMarket] = {}
        self._score_cache: Dict[str, Dict] = {}
        self._last_full_scan: Optional[datetime] = None

    async def full_discovery(self) -> List[Tuple[PolymarketMarket, Dict]]:
        """
        Full discovery scan:
        1. Fetch ALL active markets (paginated)
        2. Apply hard filters
        3. Score each market
        4. Return sorted by opportunity score (best first)
        """
        logger.info("=== Full market discovery scan ===")

        # Fetch all active markets
        raw_markets = await self.fetcher.fetch_all_active_markets(max_pages=10)
        parsed = []
        for raw in raw_markets:
            m = self.fetcher._parse_market(raw)
            if m:
                parsed.append(m)

        logger.info(f"Parsed {len(parsed)} markets from API")

        # Apply hard filters
        filtered = self._apply_hard_filters(parsed)
        logger.info(f"After hard filters: {len(filtered)} markets")

        # Score each market
        scored = []
        for market in filtered:
            score = self.scorer.score(market)
            scored.append((market, score))
            self._market_cache[market.condition_id] = market
            self._score_cache[market.condition_id] = score

        # Sort by total score descending
        scored.sort(key=lambda x: x[1]["total_score"], reverse=True)

        self._last_full_scan = datetime.utcnow()

        # Log top 10
        for i, (m, s) in enumerate(scored[:10]):
            logger.info(
                f"  #{i+1} [{s['total_score']:.0f}] {m.question[:60]} | "
                f"P={m.yes_price:.0%} Vol=${m.volume_24h:,.0f} "
                f"Days={m.days_to_resolution}"
            )

        return scored

    async def quick_rescore(
        self,
        open_position_ids: List[str] = None,
    ) -> List[Tuple[PolymarketMarket, Dict]]:
        """
        Quick rescore: re-fetch prices for cached markets + open positions.
        Much faster than full discovery — no pagination, just price updates.
        """
        if not self._market_cache:
            logger.info("No cached markets — running full discovery instead")
            return await self.full_discovery()

        # Get top candidates + open positions
        top_ids = sorted(
            self._score_cache.keys(),
            key=lambda cid: self._score_cache[cid]["total_score"],
            reverse=True,
        )[:30]

        if open_position_ids:
            all_ids = set(top_ids) | set(open_position_ids)
        else:
            all_ids = set(top_ids)

        # Rescore from cache (prices may be slightly stale but saves API calls)
        scored = []
        for cid in all_ids:
            market = self._market_cache.get(cid)
            if market:
                score = self.scorer.score(market)
                scored.append((market, score))
                self._score_cache[cid] = score

        scored.sort(key=lambda x: x[1]["total_score"], reverse=True)

        logger.info(f"Quick rescore: {len(scored)} markets rescored")
        return scored

    def get_top_markets(
        self,
        scored_markets: List[Tuple[PolymarketMarket, Dict]],
        top_n: int = None,
    ) -> List[PolymarketMarket]:
        """
        Get top N markets from scored list for full agent analysis.
        Respects DISCOVERY_TOP_N setting.
        """
        n = top_n or settings.DISCOVERY_TOP_N
        top = scored_markets[:n]

        if top:
            logger.info(
                f"Selected top {len(top)} markets for agent pipeline "
                f"(scores: {top[0][1]['total_score']:.0f} - {top[-1][1]['total_score']:.0f})"
            )

        return [m for m, _ in top]

    def _apply_hard_filters(self, markets: List[PolymarketMarket]) -> List[PolymarketMarket]:
        """Apply non-negotiable filters before scoring."""
        filtered = []
        stats = {
            "total": len(markets), "domain": 0, "volume": 0,
            "timing": 0, "prob_band": 0, "passed": 0,
        }

        focus_domains = [Domain(d) for d in settings.FOCUS_DOMAINS]

        for m in markets:
            # Domain filter
            if m.domain not in focus_domains:
                stats["domain"] += 1
                continue

            # Volume filter (use discovery-specific minimum)
            if m.volume_24h < settings.DISCOVERY_MIN_VOLUME:
                stats["volume"] += 1
                continue

            # Timing filter
            if m.days_to_resolution is not None:
                if m.days_to_resolution < 1:
                    stats["timing"] += 1
                    continue
                if m.days_to_resolution > settings.DISCOVERY_MAX_DAYS:
                    stats["timing"] += 1
                    continue

            # Probability band (tighter for discovery)
            if not (settings.DISCOVERY_PROB_MIN <= m.yes_price <= settings.DISCOVERY_PROB_MAX):
                stats["prob_band"] += 1
                continue

            filtered.append(m)
            stats["passed"] += 1

        logger.info(
            f"Discovery filter: {stats['total']} -> "
            f"-{stats['domain']} domain, -{stats['volume']} volume, "
            f"-{stats['timing']} timing, -{stats['prob_band']} prob -> "
            f"{stats['passed']} passed"
        )
        return filtered

    async def close(self):
        await self.fetcher.close()
