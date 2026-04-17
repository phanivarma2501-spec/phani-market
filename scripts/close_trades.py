"""
One-shot: manually close open paper trades at current Polymarket price.

Uses the same P&L formula as core.executor.check_open_positions().
Requires TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars.

Usage:
  python scripts/close_trades.py --dry-run 3 4 5
  python scripts/close_trades.py 3 4 5

Or via Railway CLI (picks up Railway env vars):
  railway run python scripts/close_trades.py 3 4 5
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_all_trades, close_trade
from data.polymarket import get_market_price


def close_one(trade_id: int, by_id: dict, dry_run: bool) -> dict:
    t = by_id.get(trade_id)
    if not t:
        print(f"#{trade_id}: not found")
        return {"trade_id": trade_id, "error": "not found"}
    if t.get("status") != "open":
        print(f"#{trade_id}: not open (status={t.get('status')})")
        return {"trade_id": trade_id, "error": "not open"}

    market_id = t["market_id"]
    direction = t["direction"]
    entry_price = float(t["entry_price"])
    size_usd = float(t["size_usd"])

    prices = get_market_price(market_id)
    if not prices:
        print(f"#{trade_id}: could not fetch current price for market {market_id}")
        return {"trade_id": trade_id, "error": "no price"}

    exit_price = prices["yes_price"] if direction == "YES" else prices["no_price"]
    pnl = size_usd * (exit_price - entry_price) / entry_price if entry_price > 0 else -size_usd

    tag = "[DRY-RUN]" if dry_run else "CLOSING  "
    print(
        f"{tag} #{trade_id}: {direction} @ entry {entry_price:.3f} → exit {exit_price:.3f} "
        f"| size ${size_usd:.2f} | P&L ${pnl:+.2f} | {(t.get('question') or '')[:60]}"
    )

    if not dry_run:
        close_trade(
            trade_id=trade_id,
            exit_price=round(exit_price, 4),
            pnl=round(pnl, 2),
            outcome="manual_close",
        )

    return {"trade_id": trade_id, "pnl": round(pnl, 2)}


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    if not args:
        print("Usage: python scripts/close_trades.py [--dry-run] <trade_id> [<trade_id> ...]")
        sys.exit(1)

    try:
        ids = [int(a) for a in args]
    except ValueError:
        print("All trade IDs must be integers.")
        sys.exit(1)

    if not os.environ.get("TURSO_DATABASE_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
        print("ERROR: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set.")
        sys.exit(2)

    trades = get_all_trades()
    by_id = {t["id"]: t for t in trades}

    results = [close_one(tid, by_id, dry_run) for tid in ids]
    total_pnl = sum(r.get("pnl", 0) for r in results if "pnl" in r)
    closed_n = sum(1 for r in results if "pnl" in r)

    print()
    print(f"{'[DRY-RUN] ' if dry_run else ''}{closed_n}/{len(ids)} trades {'would be ' if dry_run else ''}closed | Total P&L: ${total_pnl:+.2f}")


if __name__ == "__main__":
    main()
