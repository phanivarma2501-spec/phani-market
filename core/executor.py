from datetime import datetime
from typing import Dict, Optional
from db.database import (
    save_trade, close_trade, get_open_trades, get_portfolio_value,
    update_trade_calibrated_probability,
)
from data.polymarket import get_market_price
from core.calibration import calibrate
from core.kelly import calculate_kelly
from core.edge import check_exit
from agents.research import research_market
from agents.reasoning import estimate_probability
from settings import PAPER_TRADING, STARTING_BANKROLL, PRICE_REFRESH_THRESHOLD


def execute_paper_trade(
    market: Dict,
    direction: str,
    size_usd: float,
    entry_price: float,
    llm_probability: float,
    calibrated_probability: float,
    edge: float,
    kelly_fraction: float,
    reasoning: str
) -> Dict:
    """Execute a paper trade and save to database."""

    trade = {
        "market_id": market["id"],
        "question": market["question"],
        "direction": direction,
        "size_usd": round(size_usd, 2),
        "entry_price": entry_price,
        "llm_probability": llm_probability,
        "calibrated_probability": calibrated_probability,
        "edge": edge,
        "kelly_fraction": kelly_fraction,
        "reasoning": reasoning[:1000] if reasoning else "",
    }

    trade_id = save_trade(trade)
    trade["id"] = trade_id

    print(f"  [Executor] 📝 PAPER TRADE #{trade_id}")
    print(f"  [Executor] Market: {market['question'][:60]}...")
    print(f"  [Executor] Direction: {direction} @ {entry_price:.3f}")
    print(f"  [Executor] Size: ${size_usd:.2f} | Edge: {edge:.1%} | Kelly: {kelly_fraction:.1%}")

    return trade


def check_open_positions():
    """
    Check all open positions for exit signals or resolutions.
    Called every scan cycle. Belief is refreshed via research+reasoning
    only when the market price has moved more than PRICE_REFRESH_THRESHOLD
    on the held side since entry.
    """
    open_trades = get_open_trades()
    if not open_trades:
        return

    for trade in open_trades:
        market_id = trade["market_id"]
        direction = trade["direction"]
        entry_price = float(trade["entry_price"])
        calibrated_prob = float(trade["calibrated_probability"])
        size_usd = float(trade["size_usd"])
        question = trade["question"]

        # Get current price
        prices = get_market_price(market_id)
        if not prices:
            continue

        current_yes_price = prices["yes_price"]
        current_no_price = prices["no_price"]
        current_price = current_yes_price if direction == "YES" else current_no_price

        # Resolution detection: if Polymarket marks the market closed, settle the trade.
        # Without this, a resolved market whose price settled to 0 looks like "huge edge"
        # to check_exit and the position is held forever, blocking new trades.
        if prices.get("closed"):
            final_price = current_price
            pnl = size_usd * (final_price - entry_price) / entry_price
            if final_price >= 0.99:
                outcome = "won"
            elif final_price <= 0.01:
                outcome = "lost"
            else:
                outcome = "resolved_other"
            close_trade(
                trade_id=trade["id"],
                exit_price=final_price,
                pnl=round(pnl, 2),
                outcome=outcome,
            )
            print(
                f"  [Executor] 🏁 RESOLVED trade #{trade['id']} ({outcome}): "
                f"{direction} @ {entry_price:.3f} → {final_price:.3f} | P&L: ${pnl:.2f}"
            )
            continue

        # Belief refresh: re-run research + reasoning only if price moved enough to matter.
        # Stale beliefs were the reason positions accumulated — fresh evidence lets exits fire.
        price_delta = abs(current_price - entry_price)
        if price_delta > PRICE_REFRESH_THRESHOLD:
            print(
                f"  [Executor] Price moved {price_delta:.1%} on trade #{trade['id']} "
                f"({entry_price:.3f} → {current_price:.3f}) — refreshing belief"
            )
            try:
                minimal_market = {
                    "id": market_id, "question": question,
                    "yes_price": current_yes_price, "no_price": current_no_price,
                }
                enriched = research_market(minimal_market)
                llm_prob, _ = estimate_probability(enriched)
                if llm_prob is not None:
                    fresh_calibrated = calibrate(llm_prob)
                    update_trade_calibrated_probability(trade["id"], fresh_calibrated)
                    calibrated_prob = fresh_calibrated
                    print(f"  [Executor] Belief refreshed: {calibrated_prob:.1%}")
                else:
                    print(f"  [Executor] Refresh returned no probability — keeping stored belief")
            except Exception as e:
                print(f"  [Executor] Refresh failed for #{trade['id']}: {e} — keeping stored belief")

        # Check exit condition against current (possibly refreshed) belief
        exit_check = check_exit(calibrated_prob, direction, current_price)

        if exit_check["should_exit"]:
            pnl = size_usd * (current_price - entry_price) / entry_price
            close_trade(
                trade_id=trade["id"],
                exit_price=current_price,
                pnl=round(pnl, 2),
                outcome="exited"
            )
            print(f"  [Executor] 🚪 EXITED trade #{trade['id']}: {exit_check['reason']} | P&L: ${pnl:.2f}")
