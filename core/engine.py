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
from data.storage import Storage
from reasoning.superforecaster import SuperForecaster
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
        self.superforecaster = SuperForecaster()
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

            # Step 2: Process each market (with concurrency limit to be respectful)
            signals_this_cycle = 0
            semaphore = asyncio.Semaphore(3)  # Max 3 concurrent reasoning calls

            async def process_market(market: PolymarketMarket):
                nonlocal signals_this_cycle
                async with semaphore:
                    try:
                        # Fetch news for this market
                        news = await self.news_fetcher.fetch_for_market(market)

                        # Run structured reasoning
                        result = await self.superforecaster.reason_about_market(
                            market, news,
                            starting_capital=self.paper_trader.starting_capital
                        )
                        if not result:
                            return

                        # Save reasoning result
                        reasoning_id = await self.storage.save_reasoning(result)
                        result_dict = result.dict()

                        # Paper trade if actionable
                        if result.signal in ALERT_SIGNALS:
                            trade = await self.paper_trader.process_signal(result)
                            if trade:
                                signals_this_cycle += 1
                                self._signals_today += 1
                                await self.alerter.signal_alert(result)

                    except Exception as e:
                        self._errors_today += 1
                        logger.error(f"Error processing '{market.question[:40]}': {e}")

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

        while self._running:
            await self.run_scan_cycle()

            # Daily summary at midnight UTC
            today = datetime.utcnow().date()
            if today != last_daily:
                await self.run_daily_summary()
                last_daily = today

            if self._running:
                logger.info(f"Next scan in {settings.MARKET_SCAN_INTERVAL_MINUTES} minutes...")
                await asyncio.sleep(scan_interval)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down bot...")
        self._running = False
        await self.market_fetcher.close()
        await self.news_fetcher.close()
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        logger.info(f"Final state: {self.paper_trader.format_summary(snapshot)}")

    async def run_once(self):
        """Single scan cycle — useful for testing."""
        await self.startup()
        await self.run_scan_cycle()
        snapshot = await self.paper_trader.get_portfolio_snapshot()
        logger.info(f"Result: {self.paper_trader.format_summary(snapshot)}")
        await self.shutdown()
