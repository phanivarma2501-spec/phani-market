from flask import Flask, jsonify
from db.database import (
    get_all_trades, get_open_trades, get_brier_scores,
    get_recent_scan_logs, get_portfolio_value
)
from settings import STARTING_BANKROLL

app = Flask(__name__)

# Store last scan reasoning in memory for /reasoning endpoint
_last_reasoning = []


def update_last_reasoning(entries: list):
    global _last_reasoning
    _last_reasoning = entries[-5:]  # Keep last 5


@app.route("/")
def index():
    return jsonify({
        "service": "phani-market v2",
        "endpoints": {
            "/health": "liveness probe",
            "/debug": "portfolio value + recent scan logs",
            "/trades": "all paper trades with win/loss summary",
            "/reasoning": "R1 reasoning for the last 5 markets",
            "/calibration": "Brier scores by category",
        },
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "paper_trading": True})


@app.route("/debug")
def debug():
    """Last scan stats — markets found, edges, bets."""
    logs = get_recent_scan_logs(limit=10)
    open_trades = get_open_trades()
    bankroll = get_portfolio_value(STARTING_BANKROLL)

    return jsonify({
        "portfolio_value_usd": round(bankroll, 2),
        "starting_bankroll_usd": STARTING_BANKROLL,
        "total_pnl_usd": round(bankroll - STARTING_BANKROLL, 2),
        "open_positions": len(open_trades),
        "recent_scans": logs,
    })


@app.route("/reasoning")
def reasoning():
    """Full reasoning chain for last 5 markets analysed."""
    return jsonify({
        "count": len(_last_reasoning),
        "markets": _last_reasoning
    })


@app.route("/trades")
def trades():
    """All paper trades with P&L."""
    all_trades = get_all_trades()
    closed = [t for t in all_trades if t["status"] == "closed"]
    open_t = [t for t in all_trades if t["status"] == "open"]

    total_pnl = sum(t["pnl"] or 0 for t in closed)
    wins = [t for t in closed if (t["pnl"] or 0) > 0]
    losses = [t for t in closed if (t["pnl"] or 0) <= 0]

    return jsonify({
        "summary": {
            "total_trades": len(all_trades),
            "open": len(open_t),
            "closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed), 2) if closed else 0,
            "total_pnl_usd": round(total_pnl, 2),
        },
        "open_trades": open_t,
        "closed_trades": closed,
    })


@app.route("/calibration")
def calibration():
    """Brier scores by category."""
    scores = get_brier_scores()
    if not scores:
        return jsonify({"message": "No resolved predictions yet", "scores": []})

    # Group by category
    by_category = {}
    for s in scores:
        cat = s.get("category") or "general"
        if cat not in by_category:
            by_category[cat] = []
        if s.get("brier_score") is not None:
            by_category[cat].append(s["brier_score"])

    summary = {}
    for cat, bs in by_category.items():
        summary[cat] = {
            "count": len(bs),
            "avg_brier_score": round(sum(bs) / len(bs), 4),
            "note": "Lower is better (0=perfect, 0.25=random)"
        }

    return jsonify({"by_category": summary, "all_scores": scores})


def run_api():
    app.run(host="0.0.0.0", port=8000)
