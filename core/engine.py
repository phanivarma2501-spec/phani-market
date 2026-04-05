"""
core/engine.py
Main bot engine — orchestrates the full Phase 1 pipeline:
  Fetch markets → Filter → Fetch news → Reason → Paper trade → Alert

Runs on a schedule with graceful shutdown and error recovery.
"""

import asyncio
import signal
from datetime import datetime
from typing import List
from loguru import logger

from core.market_fetcher import MarketFetcher
from core.models import PolymarketMarket, ReasoningResult, SignalStrength
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

    Scan cycle (every 15 min):
      1. Fetch all active markets from Gamma API
      2. Filter to domain-qualified markets only
      3. For each qualified market: fetch news + run reasoning
      4. Record signals as paper trades
      5. Send alerts for actionable signals

    Daily (8am IST):
      - Send portfolio summary
      - Save portfolio snapshot
    """

    def __init__(self, starting_capital: float = 10_000.0):
        self.storage = Storage()
        self.market_fetcher = MarketFetcher()
        self.news_fetcher = NewsFetcher()
        self.cross_platform = CrossPlatformFetcher()
        self.pipeline = AgentPipeline()
        self.paper_trader = PaperTrader(self.storage, starting_capital)
        self.alerter = TelegramAlerter()

        self._running = False
        self._scan_count = 0
        self._signals_today = 0
        self._errors_today = 0

    async def startup(self):
        """Initialise all components."""
        logger.info("Starting Polymarket Bot — Phase 1 (Paper Trading Only)")
        await self.storage.init()
        await self.paper_trader.load_state()
        await self.alerter.startup_alert()
        logger.info(
            f"Bot ready | Domains: {settings.FOCUS_DOMAINS} | "
            f"Min edge: {settings.MIN_EDGE_TO_FLAG:.0%} | "
            f"Min confidence: {settings.REASONING_CONFIDENCE_MIN:.0%}"
        )

    async def run_scan_cycle(self):
        """One complete scan-reason-trade cycle."""
        self._scan_count += 1
        cycle_start = datetime.utcnow()
        logger.info(f"=== Scan #{self._scan_count} started at {cycle_start.strftime('%H:%M UTC')} ===")

        try:
            # Step 1: Fetch and filter markets
            qualified_markets = await self.market_fetcher.get_qualified_markets()
            if not qualified_markets:
                logger.warning("No qualified markets found this cycle")
                return

            logger.info(f"Processing {len(qualified_markets)} qualified markets...")

            # Update progress tracker (used by /api/debug)
            try:
                from web.app import _bot_progress
                _bot_progress["scan_number"] = self._scan_count
                _bot_progress["markets_total"] = len(qualified_markets)
                _bot_progress["markets_processed"] = 0
            except ImportError:
                _bot_progress = None

            # Step 2: Process each market sequentially through 5-agent pipeline
            signals_this_cycle = 0
            markets_done = 0
            semaphore = asyncio.Semaphore(1)  # Sequential: pipeline makes 4 LLM calls per market

            async def process_market(market: PolymarketMarket):
                nonlocal signals_this_cycle, markets_done
                async with semaphore:
                    try:
                        # Fetch news for this market
                        news = await self.news_fetcher.fetch_for_market(market)

                        # Fetch cross-platform prices (Metaculus + Kalshi)
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
                            return

                        # Save reasoning result
                        reasoning_id = await self.storage.save_reasoning(result)

                        # Track for resolution
                        cross_prices_json = self.cross_platform.serialize(cross_data) if cross_data.get("has_cross_platform") else None
                        await self.storage.track_market(
                            result, market.domain.value, cross_prices_json
                        )

                        # Paper trade if actionable (risk already checked by pipeline)
                        if result.signal in ALERT_SIGNALS:
                            trade = await self.paper_trader.process_signal(result)
                            if trade:
                                signals_this_cycle += 1
                                self._signals_today += 1
                                await self.alerter.signal_alert(result)

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

            # Process all markets concurrently (respecting semaphore)
            await asyncio.gather(*[process_market(m) for m in qualified_markets])

            # Cycle summary
            duration = (datetime.utcnow() - cycle_start).seconds
            snapshot = await self.paper_trader.get_portfolio_snapshot()
            logger.info(
                f"=== Scan #{self._scan_count} complete ({duration}s) | "
                f"Signals: {signals_this_cycle} | "
                f"{self.paper_trader.format_summary(snapshot)} ==="
            )

        except Exception as e:
            self._errors_today += 1
            logger.error(f"Scan cycle error: {e}")
            if self._errors_today <= 3:  # Don't spam on repeated errors
                await self.alerter.error_alert(str(e))

    async def run_daily_summary(self):
        """Send daily performance summary."""
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        await self.storage.save_snapshot(snapshot)
        await self.alerter.daily_summary_alert(snapshot)
        logger.info(f"Daily summary: {self.paper_trader.format_summary(snapshot)}")
        # Reset daily counters
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
        """Main run loop with scheduling."""
        self._running = True

        # Graceful shutdown on SIGINT/SIGTERM (only works in main thread)
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        except RuntimeError:
            pass  # Running in non-main thread (e.g. Railway), skip signal handlers

        await self.startup()

        scan_interval = settings.MARKET_SCAN_INTERVAL_MINUTES * 60
        last_daily = datetime.utcnow().date()
        last_weekly = datetime.utcnow().isocalendar()[1]  # ISO week number

        while self._running:
            await self.run_scan_cycle()

            today = datetime.utcnow()

            # Daily summary at midnight UTC
            if today.date() != last_daily:
                await self.run_daily_summary()
                last_daily = today.date()

            # Weekly calibration on Sundays (new ISO week)
            current_week = today.isocalendar()[1]
            if current_week != last_weekly:
                await self.run_weekly_calibration()
                last_weekly = current_week

            if self._running:
                logger.info(f"Next scan in {settings.MARKET_SCAN_INTERVAL_MINUTES} minutes...")
                await asyncio.sleep(scan_interval)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down bot...")
        self._running = False
        await self.market_fetcher.close()
        await self.news_fetcher.close()
        await self.cross_platform.close()
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        logger.info(f"Final state: {self.paper_trader.format_summary(snapshot)}")

    async def run_once(self):
        """Single scan cycle — useful for testing."""
        await self.startup()
        await self.run_scan_cycle()
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        logger.info(f"Result: {self.paper_trader.format_summary(snapshot)}")
        await self.shutdown()
