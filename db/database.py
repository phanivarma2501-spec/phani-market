import os
import libsql_client
from datetime import datetime

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")


def _get_client():
    return libsql_client.create_client_sync(
        url=TURSO_URL,
        auth_token=TURSO_TOKEN,
    )


def _rows_to_dicts(result):
    cols = [c.name for c in result.columns]
    return [dict(zip(cols, row)) for row in result.rows]


def init_db():
    client = _get_client()
    try:
        client.execute("""
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
        client.execute("""
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
        client.execute("""
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
        client.execute("""
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
    finally:
        client.close()


def save_market(market: dict):
    client = _get_client()
    try:
        client.execute(
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
    finally:
        client.close()


def save_trade(trade: dict) -> int:
    client = _get_client()
    try:
        result = client.execute(
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
        return result.last_insert_rowid
    finally:
        client.close()


def close_trade(trade_id: int, exit_price: float, pnl: float, outcome: str):
    client = _get_client()
    try:
        client.execute(
            """UPDATE trades SET status='closed', exit_price=?, pnl=?,
               resolved_outcome=?, closed_at=? WHERE id=?""",
            [exit_price, pnl, outcome, datetime.utcnow().isoformat(), trade_id]
        )
    finally:
        client.close()


def get_open_trades():
    client = _get_client()
    try:
        result = client.execute("SELECT * FROM trades WHERE status='open'")
        return _rows_to_dicts(result)
    finally:
        client.close()


def get_all_trades():
    client = _get_client()
    try:
        result = client.execute("SELECT * FROM trades ORDER BY opened_at DESC")
        return _rows_to_dicts(result)
    finally:
        client.close()


def get_portfolio_value(starting_bankroll: float) -> float:
    client = _get_client()
    try:
        result = client.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total_pnl FROM trades WHERE status='closed'"
        )
        total_pnl = result.rows[0][0] if result.rows else 0
        return starting_bankroll + (total_pnl or 0)
    finally:
        client.close()


def save_scan_log(log: dict):
    client = _get_client()
    try:
        client.execute(
            """INSERT INTO scan_logs
               (markets_found, markets_with_edge, bets_placed, errors, scanned_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                log.get("markets_found", 0), log.get("markets_with_edge", 0),
                log.get("bets_placed", 0), log.get("errors"),
                datetime.utcnow().isoformat()
            ]
        )
    finally:
        client.close()


def save_brier_score(data: dict):
    client = _get_client()
    try:
        client.execute(
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
    finally:
        client.close()


def get_brier_scores():
    client = _get_client()
    try:
        result = client.execute(
            "SELECT * FROM brier_scores WHERE brier_score IS NOT NULL ORDER BY calculated_at DESC"
        )
        return _rows_to_dicts(result)
    finally:
        client.close()


def get_recent_scan_logs(limit=10):
    client = _get_client()
    try:
        result = client.execute(
            "SELECT * FROM scan_logs ORDER BY scanned_at DESC LIMIT ?", [limit]
        )
        return _rows_to_dicts(result)
    finally:
        client.close()
