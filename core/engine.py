"""
core/engine.py
Main bot engine — orchestrates the full Phase 1 pipeline:
  Discovery → Score → Top N → News → 5-Agent Pipeline → Paper trade → Alert

Two scan cycles:
  - Full discovery (every 60 min): fetch ALL markets, score, analyze top 5
  - Quick rescore (every 15 min): rescore cached markets, analyze any new top candidates
"""

import asyncio
import signal
from datetime import datetime
from typing import List
from loguru import logger

from core.models import PolymarketMarket, ReasoningResult, SignalStrength
from core.discovery import MarketDiscovery
from data.news_fetcher import NewsFetcher
from data.cross_platform import CrossPlatformFetcher
from data.storage import Storage
from agents.pipeline import AgentPipeline
from strategies.paper_trader import PaperTrader
from utils.alerts import TelegramAlerter
from config.settings import settings

# Only alert on these signals
ALERT_SIGNALS = {SignalStrength.BUY, SignalStrength.STRONG_BUY,
                 SignalStrength.SELL, SignalStrength.STRONG_SELL}


class BotEngine:
    """
    Central orchestrator for the Phase 1 Polymarket research bot.

    Full discovery cycle (every 60 min):
      1. Fetch ALL active markets from Gamma API (paginated)
      2. Apply hard filters (volume, timing, probability band, domain)
      3. Score each by opportunity signals (price movement, volume, urgency)
      4. Select top 5 markets
      5. For each: fetch news + run 5-agent pipeline
      6. Record signals as paper trades + send alerts

    Quick rescore (every 15 min between full scans):
      - Rescore cached markets
      - Run pipeline on any new high-scoring candidates
    """

    def __init__(self, starting_capital: float = 10_000.0):
        self.storage = Storage()
        self.discovery = MarketDiscovery()
        self.news_fetcher = NewsFetcher()
        self.cross_platform = CrossPlatformFetcher()
        self.pipeline = AgentPipeline()
        self.paper_trader = PaperTrader(self.storage, starting_capital)
        self.alerter = TelegramAlerter()

        self._running = False
        self._scan_count = 0
        self._rescore_count = 0
        self._signals_today = 0
        self._errors_today = 0
        self._last_analyzed_ids: set = set()  # Track which markets we already analyzed this cycle

    async def startup(self):
        """Initialise all components."""
        logger.info("Starting Polymarket Bot — Phase 1 (Paper Trading Only)")
        logger.info("Market Discovery: automatic (no manual watchlist)")
        await self.storage.init()
        await self.paper_trader.load_state()
        await self.alerter.startup_alert()
        logger.info(
            f"Bot ready | Domains: {settings.FOCUS_DOMAINS} | "
            f"Discovery: top {settings.DISCOVERY_TOP_N} markets per scan | "
            f"Min volume: ${settings.DISCOVERY_MIN_VOLUME:,.0f} | "
            f"Max days: {settings.DISCOVERY_MAX_DAYS}"
        )

    async def _process_markets(self, markets: List[PolymarketMarket], scan_type: str):
        """Process a list of markets through the 5-agent pipeline."""
        if not markets:
            return 0

        # Update progress tracker
        try:
            from web.app import _bot_progress
            _bot_progress["scan_number"] = self._scan_count
            _bot_progress["markets_total"] = len(markets)
            _bot_progress["markets_processed"] = 0
        except ImportError:
            pass

        signals_this_cycle = 0
        markets_done = 0

        for market in markets:
            try:
                # Fetch news
                news = await self.news_fetcher.fetch_for_market(market)

                # Cross-platform prices
                cross_data = await self.cross_platform.get_cross_platform_prices(
                    market.question
                )
                cross_context = self.cross_platform.format_for_prompt(
                    cross_data, market.yes_price
                )

                # Run 5-agent pipeline
                result = await self.pipeline.run(
                    market=market,
                    news_items=news,
                    cross_platform_context=cross_context,
                    open_positions=self.paper_trader._open_trades,
                    total_capital=self.paper_trader.current_capital,
                )
                if not result:
                    continue

                # Save reasoning result
                await self.storage.save_reasoning(result)

                # Track for resolution
                cross_prices_json = self.cross_platform.serialize(cross_data) if cross_data.get("has_cross_platform") else None
                await self.storage.track_market(
                    result, market.domain.value, cross_prices_json
                )

                # Paper trade if actionable
                if result.signal in ALERT_SIGNALS:
                    trade = await self.paper_trader.process_signal(result)
                    if trade:
                        signals_this_cycle += 1
                        self._signals_today += 1
                        await self.alerter.signal_alert(result)

                # Track as analyzed
                self._last_analyzed_ids.add(market.condition_id)

            except Exception as e:
                self._errors_today += 1
                logger.error(f"Error processing '{market.question[:40]}': {e}")
            finally:
                markets_done += 1
                try:
                    from web.app import _bot_progress
                    from datetime import datetime as _dt
                    _bot_progress["markets_processed"] = markets_done
                    _bot_progress["last_market"] = market.question[:60]
                    _bot_progress["last_update"] = _dt.utcnow().isoformat()
                except ImportError:
                    pass

        return signals_this_cycle

    async def run_full_discovery(self):
        """Full discovery cycle: fetch all markets, score, analyze top N."""
        self._scan_count += 1
        cycle_start = datetime.utcnow()
        logger.info(f"=== Full Discovery #{self._scan_count} at {cycle_start.strftime('%H:%M UTC')} ===")

        try:
            # Step 1-3: Discovery + scoring + ranking
            scored_markets = await self.discovery.full_discovery()
            if not scored_markets:
                logger.warning("No markets found in discovery")
                return

            # Step 4: Select top N for full agent analysis
            top_markets = self.discovery.get_top_markets(scored_markets)
            logger.info(f"Sending {len(top_markets)} markets to 5-agent pipeline")

            # Reset analyzed set for this cycle
            self._last_analyzed_ids.clear()

            # Step 5-6: Process through pipeline
            signals = await self._process_markets(top_markets, "full_discovery")

            # Summary
            duration = (datetime.utcnow() - cycle_start).seconds
            snapshot = await self.paper_trader.get_portfolio_snapshot()
            logger.info(
                f"=== Discovery #{self._scan_count} complete ({duration}s) | "
                f"Discovered: {len(scored_markets)} | Analyzed: {len(top_markets)} | "
                f"Signals: {signals} | "
                f"{self.paper_trader.format_summary(snapshot)} ==="
            )

        except Exception as e:
            self._errors_today += 1
            logger.error(f"Discovery cycle error: {e}")
            if self._errors_today <= 3:
                await self.alerter.error_alert(str(e))

    async def run_quick_rescore(self):
        """Quick rescore: re-rank cached markets, analyze any new top candidates."""
        self._rescore_count += 1
        cycle_start = datetime.utcnow()
        logger.info(f"--- Quick Rescore #{self._rescore_count} at {cycle_start.strftime('%H:%M UTC')} ---")

        try:
            # Get open position IDs for rescore
            open_ids = [t.get("market_condition_id", "") for t in self.paper_trader._open_trades]

            # Quick rescore (no API pagination, uses cache)
            scored = await self.discovery.quick_rescore(open_position_ids=open_ids)
            if not scored:
                logger.info("No markets to rescore")
                return

            # Find NEW high-scoring markets not yet analyzed
            top = self.discovery.get_top_markets(scored)
            new_markets = [m for m in top if m.condition_id not in self._last_analyzed_ids]

            if not new_markets:
                logger.info("No new high-priority markets since last full scan")
                return

            logger.info(f"Found {len(new_markets)} new candidates for analysis")
            signals = await self._process_markets(new_markets, "quick_rescore")

            duration = (datetime.utcnow() - cycle_start).seconds
            logger.info(f"--- Rescore #{self._rescore_count} done ({duration}s) | New analyzed: {len(new_markets)} | Signals: {signals} ---")

        except Exception as e:
            self._errors_today += 1
            logger.error(f"Rescore error: {e}")

    async def run_daily_summary(self):
        """Send daily performance summary."""
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        await self.storage.save_snapshot(snapshot)
        await self.alerter.daily_summary_alert(snapshot)
        logger.info(f"Daily summary: {self.paper_trader.format_summary(snapshot)}")
        self._signals_today = 0
        self._errors_today = 0

    async def run_weekly_calibration(self):
        """Send weekly calibration report."""
        try:
            report = await self.storage.get_calibration_report()
            await self.alerter.weekly_calibration_alert(report)
            logger.info(
                f"Weekly calibration: {report.get('resolved', 0)} resolved, "
                f"accuracy={report.get('accuracy', 0):.1%}, "
                f"Brier={report.get('brier_score', 0):.3f}, "
                f"bias={report.get('bias', 'unknown')}"
            )
        except Exception as e:
            logger.error(f"Weekly calibration report failed: {e}")

    async def run(self):
        """
        Main run loop with two interleaved cycles:
          - Full discovery every 60 min
          - Quick rescore every 15 min between full scans
        """
        self._running = True

        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        except RuntimeError:
            pass

        await self.startup()

        full_interval = settings.DISCOVERY_FULL_INTERVAL_MINUTES * 60
        rescore_interval = settings.DISCOVERY_RESCORE_INTERVAL_MINUTES * 60
        last_daily = datetime.utcnow().date()
        last_weekly = datetime.utcnow().isocalendar()[1]
        last_full_scan = 0  # epoch seconds — force immediate first scan

        while self._running:
            now = datetime.utcnow()
            now_epoch = now.timestamp()

            # Full discovery every 60 min
            if now_epoch - last_full_scan >= full_interval:
                await self.run_full_discovery()
                last_full_scan = now_epoch
            else:
                # Quick rescore between full scans
                await self.run_quick_rescore()

            # Daily summary at midnight UTC
            if now.date() != last_daily:
                await self.run_daily_summary()
                last_daily = now.date()

            # Weekly calibration on Sundays
            current_week = now.isocalendar()[1]
            if current_week != last_weekly:
                await self.run_weekly_calibration()
                last_weekly = current_week

            if self._running:
                logger.info(f"Next cycle in {settings.DISCOVERY_RESCORE_INTERVAL_MINUTES} minutes...")
                await asyncio.sleep(rescore_interval)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down bot...")
        self._running = False
        await self.discovery.close()
        await self.news_fetcher.close()
        await self.cross_platform.close()
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        logger.info(f"Final state: {self.paper_trader.format_summary(snapshot)}")

    async def run_once(self):
        """Single discovery cycle — useful for testing."""
        await self.startup()
        await self.run_full_discovery()
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        logger.info(f"Result: {self.paper_trader.format_summary(snapshot)}")
        await self.shutdown()
