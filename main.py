import sys
import time
import threading
import traceback
from datetime import datetime

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from db.database import init_db, save_market, save_scan_log, get_portfolio_value
from data.polymarket import get_active_markets
from agents.research import research_market
from agents.reasoning import estimate_probability
from core.calibration import calibrate, apply_metaculus_adjustment
from core.kelly import calculate_kelly
from core.edge import check_edge
from core.executor import execute_paper_trade, check_open_positions
from api.routes import app, update_last_reasoning
from settings import (
    SCAN_INTERVAL_HOURS, PAPER_TRADING, STARTING_BANKROLL,
    EDGE_THRESHOLD_BUY, METACULUS_GAP_THRESHOLD, API_PORT
)


def run_scan():
    """Full market scan cycle."""
    scan_start = datetime.utcnow()
    print(f"\n{'='*60}")
    print(f"[Scan] Starting scan at {scan_start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*60}")

    markets_found = 0
    markets_with_edge = 0
    bets_placed = 0
    errors = []
    reasoning_log = []

    try:
        # 1. Get bankroll
        bankroll = get_portfolio_value(STARTING_BANKROLL)
        print(f"[Scan] Portfolio value: ${bankroll:.2f}")

        # 2. Check open positions for exits
        print(f"[Scan] Checking open positions...")
        check_open_positions()

        # 3. Fetch active markets
        print(f"[Scan] Fetching Polymarket markets...")
        markets = get_active_markets()
        markets_found = len(markets)
        print(f"[Scan] Found {markets_found} markets above liquidity threshold")

        if not markets:
            print("[Scan] No markets found — check Polymarket API")
            save_scan_log({
                "markets_found": 0, "markets_with_edge": 0,
                "bets_placed": 0, "errors": "No markets found"
            })
            return

        # 4. Process each market
        for i, market in enumerate(markets):
            print(f"\n[Market {i+1}/{markets_found}] {market['question'][:70]}...")
            market_log = {"question": market["question"], "id": market["id"]}

            try:
                # Save market to DB
                save_market(market)

                # Research phase
                enriched = research_market(market)
                market_log["news_found"] = enriched.get("news_context", "") != "No recent news found."
                market_log["metaculus_probability"] = enriched.get("metaculus_probability")

                # Reasoning phase
                llm_prob, full_reasoning = estimate_probability(enriched)
                market_log["llm_probability"] = llm_prob
                market_log["reasoning_snippet"] = full_reasoning[:300] if full_reasoning else ""

                if llm_prob is None:
                    print(f"  [Main] ⚠️ Could not extract probability — skipping")
                    market_log["skipped_reason"] = "No probability extracted"
                    reasoning_log.append(market_log)
                    continue

                print(f"  [Main] LLM probability: {llm_prob:.1%}")

                # Single-pass calibration
                calibrated = calibrate(llm_prob)
                print(f"  [Main] Calibrated probability: {calibrated:.1%}")

                # Metaculus adjustment (if available and gap significant)
                metaculus_prob = enriched.get("metaculus_probability")
                final_prob, metaculus_used = apply_metaculus_adjustment(
                    calibrated, metaculus_prob, METACULUS_GAP_THRESHOLD
                )

                if metaculus_used:
                    print(f"  [Main] Metaculus adjustment applied: {calibrated:.1%} → {final_prob:.1%}")

                market_log["calibrated_probability"] = final_prob
                market_log["metaculus_used"] = metaculus_used

                # Kelly sizing
                yes_price = market.get("yes_price", 0.5)
                kelly = calculate_kelly(final_prob, yes_price, bankroll)
                direction = kelly["direction"]
                edge = kelly["edge"]
                size_usd = kelly["size_usd"]
                entry_price = yes_price if direction == "YES" else market.get("no_price", 0.5)

                market_log["direction"] = direction
                market_log["edge"] = edge
                market_log["size_usd"] = size_usd
                market_log["entry_price"] = entry_price

                print(f"  [Main] Direction: {direction} | Edge: {edge:.1%} | Size: ${size_usd:.2f} @ {entry_price:.3f}")

                # Edge gate
                gate = check_edge(kelly, size_usd, entry_price)
                market_log["gate_result"] = gate["reason"]
                market_log["signal_strength"] = gate["signal_strength"]

                if not gate["should_bet"]:
                    print(f"  [Main] ⛔ Gate blocked: {gate['reason']}")
                    reasoning_log.append(market_log)
                    continue

                markets_with_edge += 1
                print(f"  [Main] ✅ Edge gate passed: {gate['reason']}")

                # Execute paper trade
                trade = execute_paper_trade(
                    market=enriched,
                    direction=direction,
                    size_usd=size_usd,
                    entry_price=entry_price,
                    llm_probability=llm_prob,
                    calibrated_probability=final_prob,
                    edge=edge,
                    kelly_fraction=kelly["kelly_fraction"],
                    reasoning=full_reasoning,
                )
                bets_placed += 1
                market_log["trade_placed"] = True
                market_log["trade_id"] = trade.get("id")

            except Exception as e:
                err_msg = f"Market {market['id']}: {str(e)}"
                print(f"  [Main] ❌ Error: {err_msg}")
                errors.append(err_msg)
                market_log["error"] = err_msg

            reasoning_log.append(market_log)

        # Update reasoning endpoint
        update_last_reasoning(reasoning_log)

    except Exception as e:
        err = traceback.format_exc()
        print(f"[Scan] ❌ Fatal error: {err}")
        errors.append(str(e))

    finally:
        # Save scan log
        save_scan_log({
            "markets_found": markets_found,
            "markets_with_edge": markets_with_edge,
            "bets_placed": bets_placed,
            "errors": "; ".join(errors) if errors else None,
        })

        duration = (datetime.utcnow() - scan_start).seconds
        print(f"\n[Scan] ✅ Complete in {duration}s")
        print(f"[Scan] Markets: {markets_found} | With edge: {markets_with_edge} | Bets placed: {bets_placed}")
        if errors:
            print(f"[Scan] ⚠️ Errors: {errors}")


def scheduler():
    """Run scan every SCAN_INTERVAL_HOURS."""
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"[Scheduler] Unhandled error: {e}")
        interval_seconds = SCAN_INTERVAL_HOURS * 3600
        print(f"\n[Scheduler] Next scan in {SCAN_INTERVAL_HOURS} hour(s)...")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    print("🚀 phani-market v2 starting...")
    print(f"   Paper trading: {PAPER_TRADING}")
    print(f"   Scan interval: {SCAN_INTERVAL_HOURS} hour(s)")
    print(f"   Starting bankroll: ${STARTING_BANKROLL:,.0f}")

    # Initialise database
    init_db()

    # Kick off scans in the background — scheduler runs the first scan immediately,
    # so Flask can start serving (and Railway's healthcheck can pass) without waiting.
    t = threading.Thread(target=scheduler, daemon=True)
    t.start()

    # Flask blocks here as the main thread
    print(f"\n[API] Starting on port {API_PORT}...")
    app.run(host="0.0.0.0", port=API_PORT, use_reloader=False)
