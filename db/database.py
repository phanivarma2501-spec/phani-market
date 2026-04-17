import os
import requests
from datetime import datetime

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")


def _http_base():
    url = TURSO_URL
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url.rstrip("/")


def _convert_param(value):
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    return {"type": "text", "value": str(value)}


def _extract_value(cell):
    if cell is None:
        return None
    t = cell.get("type")
    v = cell.get("value")
    if t == "null" or v is None:
        return None
    if t == "integer":
        return int(v)
    if t == "float":
        return float(v)
    return v


def _execute(sql, params=None):
    stmt = {"sql": sql}
    if params:
        stmt["args"] = [_convert_param(p) for p in params]
    body = {"requests": [
        {"type": "execute", "stmt": stmt},
        {"type": "close"},
    ]}
    resp = requests.post(
        f"{_http_base()}/v3/pipeline",
        json=body,
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return {}
    first = results[0]
    if first.get("type") == "error":
        err = first.get("error", {})
        raise RuntimeError(f"Turso SQL error: {err.get('message', str(err))}")
    response = first.get("response", {})
    return response.get("result", {})


def _rows_to_dicts(result):
    cols = [c.get("name") for c in result.get("cols", [])]
    out = []
    for row in result.get("rows", []):
        values = [_extract_value(cell) for cell in row]
        out.append(dict(zip(cols, values)))
    return out


def init_db():
    _execute("""
        CREATE TABLE IF NOT EXISTS markets (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            category TEXT,
            end_date TEXT,
            liquidity_usd REAL,
            yes_price REAL,
            no_price REAL,
            metaculus_probability REAL,
            gdelt_sentiment TEXT,
            scanned_at TEXT NOT NULL
        )
    """)
    _execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            question TEXT NOT NULL,
            direction TEXT NOT NULL,
            size_usd REAL NOT NULL,
            entry_price REAL NOT NULL,
            llm_probability REAL NOT NULL,
            calibrated_probability REAL NOT NULL,
            edge REAL NOT NULL,
            kelly_fraction REAL NOT NULL,
            reasoning TEXT,
            status TEXT DEFAULT 'open',
            exit_price REAL,
            pnl REAL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            resolved_outcome TEXT
        )
    """)
    _execute("""
        CREATE TABLE IF NOT EXISTS brier_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            market_id TEXT NOT NULL,
            category TEXT,
            predicted_probability REAL NOT NULL,
            actual_outcome REAL,
            brier_score REAL,
            calculated_at TEXT
        )
    """)
    _execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            markets_found INTEGER,
            markets_with_edge INTEGER,
            bets_placed INTEGER,
            errors TEXT,
            scanned_at TEXT NOT NULL
        )
    """)
    print("Turso DB initialised.")


def save_market(market: dict):
    _execute(
        """INSERT OR REPLACE INTO markets
           (id, question, category, end_date, liquidity_usd, yes_price, no_price,
            metaculus_probability, gdelt_sentiment, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            market["id"], market["question"], market.get("category"),
            market.get("end_date"), market.get("liquidity_usd"),
            market.get("yes_price"), market.get("no_price"),
            market.get("metaculus_probability"), market.get("gdelt_sentiment"),
            datetime.utcnow().isoformat()
        ]
    )


def save_trade(trade: dict) -> int:
    result = _execute(
        """INSERT INTO trades
           (market_id, question, direction, size_usd, entry_price, llm_probability,
            calibrated_probability, edge, kelly_fraction, reasoning, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            trade["market_id"], trade["question"], trade["direction"],
            trade["size_usd"], trade["entry_price"], trade["llm_probability"],
            trade["calibrated_probability"], trade["edge"], trade["kelly_fraction"],
            trade.get("reasoning"), datetime.utcnow().isoformat()
        ]
    )
    rowid = result.get("last_insert_rowid")
    return int(rowid) if rowid is not None else 0


def close_trade(trade_id: int, exit_price: float, pnl: float, outcome: str):
    _execute(
        """UPDATE trades SET status='closed', exit_price=?, pnl=?,
           resolved_outcome=?, closed_at=? WHERE id=?""",
        [exit_price, pnl, outcome, datetime.utcnow().isoformat(), trade_id]
    )


def get_open_trades():
    return _rows_to_dicts(_execute("SELECT * FROM trades WHERE status='open'"))


def get_all_trades():
    return _rows_to_dicts(_execute("SELECT * FROM trades ORDER BY opened_at DESC"))


def get_portfolio_value(starting_bankroll: float) -> float:
    result = _execute(
        "SELECT COALESCE(SUM(pnl), 0) as total_pnl FROM trades WHERE status='closed'"
    )
    rows = result.get("rows") or []
    total_pnl = _extract_value(rows[0][0]) if rows else 0
    return starting_bankroll + (total_pnl or 0)


def save_scan_log(log: dict):
    _execute(
        """INSERT INTO scan_logs
           (markets_found, markets_with_edge, bets_placed, errors, scanned_at)
           VALUES (?, ?, ?, ?, ?)""",
        [
            log.get("markets_found", 0), log.get("markets_with_edge", 0),
            log.get("bets_placed", 0), log.get("errors"),
            datetime.utcnow().isoformat()
        ]
    )


def save_brier_score(data: dict):
    _execute(
        """INSERT INTO brier_scores
           (trade_id, market_id, category, predicted_probability,
            actual_outcome, brier_score, calculated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            data["trade_id"], data["market_id"], data.get("category"),
            data["predicted_probability"], data.get("actual_outcome"),
            data.get("brier_score"), datetime.utcnow().isoformat()
        ]
    )


def get_brier_scores():
    return _rows_to_dicts(_execute(
        "SELECT * FROM brier_scores WHERE brier_score IS NOT NULL ORDER BY calculated_at DESC"
    ))


def get_recent_scan_logs(limit=10):
    return _rows_to_dicts(_execute(
        "SELECT * FROM scan_logs ORDER BY scanned_at DESC LIMIT ?", [limit]
    ))
