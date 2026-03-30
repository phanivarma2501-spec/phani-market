"""
main.py - Polymarket Research Bot, Phase 1
Entry point. Run with: python main.py [command]

Commands:
  run       - Full continuous scan loop (default)
  once      - Single scan cycle, then exit
  status    - Print portfolio status and exit
  test      - Fetch markets and show filter results (no reasoning)
"""

import asyncio
import sys
from loguru import logger
from pathlib import Path

# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/bot.log",
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
)

from core.engine import BotEngine
from core.market_fetcher import MarketFetcher
from data.storage import Storage
from config.settings import settings


async def cmd_run():
    """Full continuous scan loop."""
    engine = BotEngine(starting_capital=10_000.0)
    await engine.run()


async def cmd_once():
    """Single scan cycle."""
    engine = BotEngine(starting_capital=10_000.0)
    await engine.run_once()


async def cmd_status():
    """Print current portfolio status."""
    storage = Storage()
    await storage.init()
    perf = await storage.get_performance_summary()
    print("\n[Portfolio Status] Phase 1 - Paper Trading")
    print("=" * 50)
    print(f"  Total trades:    {perf['total_trades']}")
    print(f"  Open positions:  {perf['open_trades']}")
    print(f"  Closed trades:   {perf['closed_trades']}")
    print(f"  Win rate:        {perf['win_rate']:.0%}")
    print(f"  Total P&L:       ${perf['total_pnl_usd']:+,.2f}")
    print(f"  Deployed:        ${perf['deployed_capital']:,.2f}")
    print(f"  Avg edge (wins): {perf['avg_edge_on_wins']:.1%}")
    print("=" * 50)


async def cmd_test():
    """Fetch markets, show filter results - no reasoning or API cost."""
    logger.info("TEST MODE - fetching markets, showing filter results")
    fetcher = MarketFetcher()
    try:
        markets = await fetcher.get_qualified_markets()
        print(f"\n[OK] Qualified markets: {len(markets)}")
        print("-" * 60)
        for m in markets[:10]:
            print(
                f"[{m.domain.value.upper():8}] {m.question[:55]:<55} "
                f"P={m.yes_price:.0%} Vol=${m.volume_24h:,.0f} "
                f"Days={m.days_to_resolution}"
            )
        if len(markets) > 10:
            print(f"  ... and {len(markets) - 10} more")
    finally:
        await fetcher.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    commands = {
        "run": cmd_run,
        "once": cmd_once,
        "status": cmd_status,
        "test": cmd_test,
    }
    if cmd not in commands:
        print(f"Unknown command: {cmd}. Use: {', '.join(commands)}")
        sys.exit(1)

    # Phase 1 safety check
    if settings.LIVE_TRADING_ENABLED:
        print("[ERROR] LIVE_TRADING_ENABLED=True in Phase 1. Set it to False.")
        sys.exit(1)

    asyncio.run(commands[cmd]())
