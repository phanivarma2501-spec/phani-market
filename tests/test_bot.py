"""
tests/test_bot.py
Smoke tests — run these before deploying.
Tests core logic without calling paid APIs.
"""

import asyncio
import sys
sys.path.insert(0, '/home/claude/polymarket_bot')

from core.models import (
    PolymarketMarket, OutcomeToken, Domain,
    ReasoningResult, SignalStrength
)
from reasoning.superforecaster import platt_scale, SuperForecaster
from strategies.paper_trader import PaperTrader
from data.storage import Storage


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_platt_scale():
    """scale=0.7 compresses extreme estimates toward 0.5."""
    assert platt_scale(0.9) < 0.9,   "Should compress 0.9 toward 0.5"
    assert platt_scale(0.9) > 0.5,   "Should still be above 0.5"
    assert platt_scale(0.1) > 0.1,   "Should compress 0.1 toward 0.5"
    assert platt_scale(0.1) < 0.5,   "Should still be below 0.5"
    assert abs(platt_scale(0.5) - 0.5) < 0.01, "Midpoint should not shift"
    assert abs(platt_scale(0.7) + platt_scale(0.3) - 1.0) < 0.01, "Symmetric"
    print(f"  platt_scale(0.9)={platt_scale(0.9):.3f}  platt_scale(0.1)={platt_scale(0.1):.3f}")


def test_signal_thresholds():
    """Signal determination logic."""
    sf = SuperForecaster.__new__(SuperForecaster)

    # Strong buy: large edge + high confidence
    sig = sf._determine_signal(0.15, 0.80, 0.70, 0.55)
    assert sig == SignalStrength.STRONG_BUY, f"Expected STRONG_BUY, got {sig}"

    # Regular buy: moderate edge
    sig = sf._determine_signal(0.08, 0.70, 0.63, 0.55)
    assert sig == SignalStrength.BUY, f"Expected BUY, got {sig}"

    # Hold: low confidence
    sig = sf._determine_signal(0.10, 0.60, 0.65, 0.55)
    assert sig == SignalStrength.HOLD, f"Expected HOLD, got {sig}"

    # Hold: tiny edge
    sig = sf._determine_signal(0.04, 0.80, 0.59, 0.55)
    assert sig == SignalStrength.HOLD, f"Expected HOLD (small edge), got {sig}"

    # Sell: negative edge
    sig = sf._determine_signal(-0.09, 0.72, 0.41, 0.50)
    assert sig == SignalStrength.SELL, f"Expected SELL, got {sig}"

    # Strong sell
    sig = sf._determine_signal(-0.14, 0.80, 0.38, 0.52)
    assert sig == SignalStrength.STRONG_SELL, f"Expected STRONG_SELL, got {sig}"


def test_kelly_sizing():
    """Kelly calculation respects limits."""
    sf = SuperForecaster.__new__(SuperForecaster)

    # Real edge: our 0.70 vs market 0.55
    full_k, pos_pct, pos_usd = sf._calculate_kelly(0.70, 0.55, 0.80, 10_000.0)
    assert full_k > 0,       "Should have positive Kelly"
    assert pos_pct <= 0.05,  "Must not exceed 5% max position"
    assert pos_usd <= 500,   "Must not exceed $500 on $10k capital"
    print(f"  Kelly: full={full_k:.3f} pos_pct={pos_pct:.3f} pos_usd=${pos_usd:.2f}")

    # No edge
    full_k, pos_pct, pos_usd = sf._calculate_kelly(0.50, 0.55, 0.80, 10_000.0)
    assert pos_usd == 0.0, "No edge = no position"

    # Low confidence should reduce size
    _, pos_pct_hi, _ = sf._calculate_kelly(0.70, 0.55, 0.80, 10_000.0)
    _, pos_pct_lo, _ = sf._calculate_kelly(0.70, 0.55, 0.66, 10_000.0)
    assert pos_pct_lo < pos_pct_hi, "Lower confidence = smaller position"


def test_market_classification():
    """Domain classifier correctly tags markets."""
    from core.market_fetcher import MarketFetcher
    fetcher = MarketFetcher()

    cases = [
        ({"question": "Will Bitcoin hit $100k?", "description": "", "category": "crypto", "tags": []},
         Domain.CRYPTO),
        ({"question": "Will Trump win the 2026 midterms?", "description": "", "category": "politics", "tags": []},
         Domain.POLITICS),
        ({"question": "Will the Fed cut rates in March 2026?", "description": "", "category": "economics", "tags": []},
         Domain.ECONOMICS),
        ({"question": "Will it rain in Mumbai tomorrow?", "description": "", "category": "", "tags": []},
         Domain.OTHER),
    ]
    for market_dict, expected in cases:
        result = fetcher._classify_domain(market_dict)
        assert result == expected, f"'{market_dict['question'][:40]}': expected {expected}, got {result}"


def test_market_filter_logic():
    """Market filter rejects illiquid/out-of-band/wrong-domain markets."""
    from core.market_fetcher import MarketFetcher
    from datetime import datetime, timezone, timedelta
    fetcher = MarketFetcher()

    def make_market(**kwargs):
        defaults = dict(
            condition_id="test", question="Will BTC hit $100k?",
            domain=Domain.CRYPTO, yes_price=0.55, no_price=0.45,
            volume_24h=5000, liquidity=10000, days_to_resolution=30,
            active=True, closed=False,
        )
        defaults.update(kwargs)
        return PolymarketMarket(**defaults)

    # Good market passes
    good = make_market()
    assert fetcher.filter_markets([good]) == [good]

    # Illiquid market rejected
    illiquid = make_market(liquidity=100)
    assert fetcher.filter_markets([illiquid]) == []

    # Low volume rejected
    low_vol = make_market(volume_24h=50)
    assert fetcher.filter_markets([low_vol]) == []

    # Near-certainty rejected
    certain = make_market(yes_price=0.97)
    assert fetcher.filter_markets([certain]) == []

    # Wrong domain rejected
    wrong_domain = make_market(domain=Domain.OTHER, question="Will it rain?")
    assert fetcher.filter_markets([wrong_domain]) == []

    # Expired market rejected
    expired = make_market(days_to_resolution=0)
    assert fetcher.filter_markets([expired]) == []


# ── Async integration tests ───────────────────────────────────────────────────

async def test_paper_trader_opens_position():
    """Paper trader opens position on STRONG_BUY."""
    import tempfile, os; _tf = tempfile.mktemp(suffix=".db"); storage = Storage(db_path=_tf)
    await storage.init()
    trader = PaperTrader(storage, starting_capital=10_000.0)

    result = ReasoningResult(
        market_condition_id="test-001",
        market_question="Will BTC be above $90k end of April 2026?",
        our_probability=0.72,
        market_probability=0.55,
        edge=0.17,
        confidence=0.79,
        signal=SignalStrength.STRONG_BUY,
        kelly_fraction=0.10,
        suggested_position_pct=0.04,
        suggested_position_usd=400.0,
    )

    trade = await trader.process_signal(result)
    assert trade is not None, "Should open trade on STRONG_BUY"
    assert trade.side == "YES"
    assert trade.size_usd <= 500, f"Size ${trade.size_usd} exceeds $500 limit"

    # Duplicate blocked
    trade2 = await trader.process_signal(result)
    assert trade2 is None, "Duplicate position should be blocked"


async def test_paper_trader_hold_no_trade():
    """Paper trader does NOT open position on HOLD."""
    import tempfile, os; _tf = tempfile.mktemp(suffix=".db"); storage = Storage(db_path=_tf)
    await storage.init()
    trader = PaperTrader(storage, starting_capital=10_000.0)

    result = ReasoningResult(
        market_condition_id="test-002",
        market_question="Will ETH flip BTC market cap in 2026?",
        our_probability=0.52,
        market_probability=0.50,
        edge=0.02,
        confidence=0.55,
        signal=SignalStrength.HOLD,
        suggested_position_usd=0.0,
    )
    trade = await trader.process_signal(result)
    assert trade is None, "HOLD signal should not open trade"


async def test_storage_round_trip():
    """Save and retrieve reasoning result from DB."""
    from core.models import ReasoningResult, SignalStrength
    import tempfile, os; _tf = tempfile.mktemp(suffix=".db"); storage = Storage(db_path=_tf)
    await storage.init()

    result = ReasoningResult(
        market_condition_id="mkt-001",
        market_question="Will Fed cut rates in May 2026?",
        our_probability=0.61,
        market_probability=0.48,
        edge=0.13,
        confidence=0.74,
        signal=SignalStrength.BUY,
        suggested_position_usd=250.0,
    )
    rid = await storage.save_reasoning(result)
    assert rid, "Should return a UUID"

    rows = await storage.get_recent_reasoning("mkt-001")
    assert len(rows) == 1
    assert abs(rows[0]["our_probability"] - 0.61) < 0.001


async def test_portfolio_performance():
    """Performance summary returns correct stats."""
    import tempfile, os; _tf = tempfile.mktemp(suffix=".db"); storage = Storage(db_path=_tf)
    await storage.init()
    trader = PaperTrader(storage, starting_capital=10_000.0)

    # Open and close two trades
    for i, (edge, conf) in enumerate([(0.15, 0.80), (0.10, 0.72)]):
        result = ReasoningResult(
            market_condition_id=f"mkt-perf-{i}",
            market_question=f"Market {i}",
            our_probability=0.55 + edge,
            market_probability=0.55,
            edge=edge,
            confidence=conf,
            signal=SignalStrength.BUY,
            suggested_position_usd=200.0,
        )
        await trader.process_signal(result)

    perf = await storage.get_performance_summary()
    assert perf["total_trades"] == 2
    assert perf["open_trades"] == 2
    assert perf["closed_trades"] == 0


if __name__ == "__main__":
    print("\n🧪 Running unit tests...")

    test_platt_scale()
    print("  ✅ Platt scaling")

    test_signal_thresholds()
    print("  ✅ Signal thresholds")

    test_kelly_sizing()
    print("  ✅ Kelly sizing")

    test_market_classification()
    print("  ✅ Market classification")

    test_market_filter_logic()
    print("  ✅ Market filter logic")

    print("\n🔄 Running async integration tests...")

    asyncio.run(test_paper_trader_opens_position())
    print("  ✅ Paper trader opens position")

    asyncio.run(test_paper_trader_hold_no_trade())
    print("  ✅ Paper trader respects HOLD")

    asyncio.run(test_storage_round_trip())
    print("  ✅ Storage round-trip")

    asyncio.run(test_portfolio_performance())
    print("  ✅ Portfolio performance stats")

    print("\n✅ All tests passed!\n")
