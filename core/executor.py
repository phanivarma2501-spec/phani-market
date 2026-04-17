from datetime import datetime
from typing import Dict, Optional
from db.database import save_trade, close_trade, get_open_trades, get_portfolio_value
from data.polymarket import get_market_price
from core.calibration import calibrate
from core.kelly import calculate_kelly
from core.edge import check_exit
from settings import PAPER_TRADING, STARTING_BANKROLL


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
    Called every scan cycle.
    """
    open_trades = get_open_trades()
    if not open_trades:
        return

    bankroll = get_portfolio_value(STARTING_BANKROLL)

    for trade in open_trades:
        market_id = trade["market_id"]
        direction = trade["direction"]
        entry_price = float(trade["entry_price"])
        calibrated_prob = float(trade["calibrated_probability"])
        size_usd = float(trade["size_usd"])

        # Get current price
        prices = get_market_price(market_id)
        if not prices:
            continue

        current_yes_price = prices["yes_price"]
        current_no_price = prices["no_price"]

        # Recalibrate probability with current price context
        current_price = current_yes_price if direction == "YES" else current_no_price

        # Check exit condition
        exit_check = check_exit(calibrated_prob, direction, current_price)

        if exit_check["should_exit"]:
            # Calculate P&L
            if direction == "YES":
                pnl = size_usd * (current_yes_price - entry_price) / entry_price
            else:
                pnl = size_usd * (current_no_price - entry_price) / entry_price

            close_trade(
                trade_id=trade["id"],
                exit_price=current_price,
                pnl=round(pnl, 2),
                outcome="exited"
            )
            print(f"  [Executor] 🚪 EXITED trade #{trade['id']}: {exit_check['reason']} | P&L: ${pnl:.2f}")
