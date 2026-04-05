"""
data/storage.py
SQLite-based storage for reasoning results, paper trades, and portfolio state.
All Phase 1 data stays local — nothing sent to external services.
"""

import aiosqlite
import json
import uuid
from datetime import datetime
from typing import List, Optional
from pathlib import Path
from loguru import logger

from core.models import ReasoningResult, PaperTrade, PortfolioSnapshot, SignalStrength, Domain
from config.settings import settings
from data.turso_client import connect as turso_connect


class Storage:
    """Async storage — uses Turso cloud when configured, local SQLite otherwise."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        """Connect to Turso (cloud) or local SQLite."""
        return turso_connect(self.db_path)

    async def init(self):
        """Create all tables on first run."""
        async with self._connect() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reasoning_results (
                    id TEXT PRIMARY KEY,
                    market_condition_id TEXT NOT NULL,
                    market_question TEXT NOT NULL,
                    our_probability REAL,
                    market_probability REAL,
                    edge REAL,
                    confidence REAL,
                    signal TEXT,
                    reference_class TEXT,
                    base_rate_used TEXT,
                    raw_llm_probability REAL,
                    calibration_adjustment REAL,
                    calibration_note TEXT,
                    kelly_fraction REAL,
                    suggested_position_pct REAL,
                    suggested_position_usd REAL,
                    steps_json TEXT,
                    news_urls_json TEXT,
                    reasoned_at TEXT,
                    valid_until TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id TEXT PRIMARY KEY,
                    market_condition_id TEXT NOT NULL,
                    market_question TEXT NOT NULL,
                    side TEXT,
                    entry_price REAL,
                    size_usd REAL,
                    signal TEXT,
                    our_probability REAL,
                    market_probability REAL,
                    edge REAL,
                    confidence REAL,
                    domain TEXT,
                    exit_price REAL,
                    resolved INTEGER DEFAULT 0,
                    resolution_outcome TEXT,
                    pnl_usd REAL,
                    pnl_pct REAL,
                    entered_at TEXT,
                    exited_at TEXT,
                    reasoning_id TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    starting_capital REAL,
                    current_capital REAL,
                    deployed_capital REAL,
                    total_pnl REAL,
                    total_return_pct REAL,
                    open_positions INTEGER,
                    closed_positions INTEGER,
                    win_rate REAL,
                    avg_edge_captured REAL,
                    phase INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS resolution_tracker (
                    id TEXT PRIMARY KEY,
                    market_condition_id TEXT NOT NULL,
                    market_question TEXT NOT NULL,
                    domain TEXT,
                    our_probability REAL,
                    market_probability REAL,
                    edge REAL,
                    confidence REAL,
                    signal TEXT,
                    flagged_at TEXT NOT NULL,
                    resolution_status TEXT DEFAULT 'PENDING',
                    resolution_outcome TEXT,
                    resolved_at TEXT,
                    was_correct INTEGER,
                    prediction_error REAL,
                    cross_platform_prices TEXT
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_reasoning_market
                ON reasoning_results(market_condition_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_market
                ON paper_trades(market_condition_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_resolution_market
                ON resolution_tracker(market_condition_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_resolution_status
                ON resolution_tracker(resolution_status)
            """)
            await db.commit()
        logger.info(f"Storage initialised at {self.db_path}")

    async def save_reasoning(self, result: ReasoningResult) -> str:
        """Persist a reasoning result. Returns the generated ID."""
        rid = str(uuid.uuid4())
        async with self._connect() as db:
            await db.execute("""
                INSERT OR REPLACE INTO reasoning_results VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                rid,
                result.market_condition_id,
                result.market_question,
                result.our_probability,
                result.market_probability,
                result.edge,
                result.confidence,
                result.signal.value,
                result.reference_class,
                result.base_rate_used,
                result.raw_llm_probability,
                result.calibration_adjustment,
                result.calibration_note,
                result.kelly_fraction,
                result.suggested_position_pct,
                result.suggested_position_usd,
                json.dumps([s.dict() for s in result.steps]),
                json.dumps(result.news_items_used),
                result.reasoned_at.isoformat(),
                result.valid_until.isoformat() if result.valid_until else None,
            ))
            await db.commit()
        return rid

    async def save_paper_trade(self, trade: PaperTrade) -> str:
        """Record a paper trade. Returns ID."""
        tid = trade.id or str(uuid.uuid4())
        async with self._connect() as db:
            await db.execute("""
                INSERT OR REPLACE INTO paper_trades VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                tid,
                trade.market_condition_id,
                trade.market_question,
                trade.side,
                trade.entry_price,
                trade.size_usd,
                trade.signal.value,
                trade.our_probability,
                trade.market_probability,
                trade.edge,
                trade.confidence,
                trade.domain.value,
                trade.exit_price,
                int(trade.resolved),
                trade.resolution_outcome,
                trade.pnl_usd,
                trade.pnl_pct,
                trade.entered_at.isoformat(),
                trade.exited_at.isoformat() if trade.exited_at else None,
                trade.reasoning_id,
            ))
            await db.commit()
        return tid

    async def get_open_trades(self) -> List[dict]:
        """Get all unresolved paper trades."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM paper_trades WHERE resolved = 0 ORDER BY entered_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_recent_reasoning(
        self, market_condition_id: str, limit: int = 3
    ) -> List[dict]:
        """Get recent reasoning results for a market."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM reasoning_results
                   WHERE market_condition_id = ?
                   ORDER BY reasoned_at DESC LIMIT ?""",
                (market_condition_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_performance_summary(self) -> dict:
        """Calculate live performance stats from paper trades."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("SELECT COUNT(*) as total FROM paper_trades") as c:
                total = (await c.fetchone())["total"]

            async with db.execute(
                "SELECT COUNT(*) as closed FROM paper_trades WHERE resolved = 1"
            ) as c:
                closed = (await c.fetchone())["closed"]

            async with db.execute(
                "SELECT COUNT(*) as wins FROM paper_trades WHERE resolved = 1 AND pnl_usd > 0"
            ) as c:
                wins = (await c.fetchone())["wins"]

            async with db.execute(
                "SELECT COALESCE(SUM(pnl_usd), 0) as total_pnl FROM paper_trades WHERE resolved = 1"
            ) as c:
                total_pnl = (await c.fetchone())["total_pnl"]

            async with db.execute(
                "SELECT COALESCE(SUM(size_usd), 0) as deployed FROM paper_trades WHERE resolved = 0"
            ) as c:
                deployed = (await c.fetchone())["deployed"]

            async with db.execute(
                "SELECT COALESCE(AVG(ABS(edge)), 0) as avg_edge FROM paper_trades WHERE resolved = 1 AND pnl_usd > 0"
            ) as c:
                avg_edge = (await c.fetchone())["avg_edge"]

        win_rate = (wins / closed) if closed > 0 else 0.0
        return {
            "total_trades": total,
            "closed_trades": closed,
            "open_trades": total - closed,
            "wins": wins,
            "win_rate": round(win_rate, 4),
            "total_pnl_usd": round(total_pnl, 2),
            "deployed_capital": round(deployed, 2),
            "avg_edge_on_wins": round(avg_edge, 4),
        }

    # ── Resolution Tracker ─────────────────────────────────────────────────

    async def track_market(self, result: ReasoningResult, domain: str,
                           cross_platform_prices: str = None) -> str:
        """Log every flagged market for resolution tracking."""
        tid = str(uuid.uuid4())
        async with self._connect() as db:
            # Skip if already tracked
            async with db.execute(
                "SELECT id FROM resolution_tracker WHERE market_condition_id = ? AND resolution_status = 'PENDING'",
                (result.market_condition_id,)
            ) as c:
                if await c.fetchone():
                    return ""
            await db.execute("""
                INSERT INTO resolution_tracker VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                tid, result.market_condition_id, result.market_question,
                domain, result.our_probability, result.market_probability,
                result.edge, result.confidence, result.signal.value,
                result.reasoned_at.isoformat(), "PENDING",
                None, None, None, None, cross_platform_prices,
            ))
            await db.commit()
        return tid

    async def resolve_market(self, market_condition_id: str, outcome: str):
        """Mark a tracked market as resolved and compute accuracy."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT id, our_probability FROM resolution_tracker WHERE market_condition_id = ? AND resolution_status = 'PENDING'",
                (market_condition_id,)
            ) as c:
                row = await c.fetchone()
            if not row:
                return
            tid = row[0]
            our_prob = row[1]
            actual = 1.0 if outcome == "YES" else 0.0
            was_correct = 1 if (our_prob >= 0.5 and outcome == "YES") or (our_prob < 0.5 and outcome == "NO") else 0
            prediction_error = abs(our_prob - actual)
            now = datetime.utcnow().isoformat()
            await db.execute("""
                UPDATE resolution_tracker SET
                    resolution_status='RESOLVED', resolution_outcome=?,
                    resolved_at=?, was_correct=?, prediction_error=?
                WHERE id=?
            """, (outcome, now, was_correct, round(prediction_error, 4), tid))
            await db.commit()

    async def get_resolution_stats(self) -> dict:
        """Get calibration stats from resolved markets."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT COUNT(*) as total FROM resolution_tracker") as c:
                total = (await c.fetchone())["total"]
            async with db.execute("SELECT COUNT(*) as resolved FROM resolution_tracker WHERE resolution_status='RESOLVED'") as c:
                resolved = (await c.fetchone())["resolved"]
            async with db.execute("SELECT COUNT(*) as correct FROM resolution_tracker WHERE was_correct=1") as c:
                correct = (await c.fetchone())["correct"]
            async with db.execute("SELECT COALESCE(AVG(prediction_error), 0) as avg_err FROM resolution_tracker WHERE resolution_status='RESOLVED'") as c:
                avg_err = (await c.fetchone())["avg_err"]
            async with db.execute("SELECT COUNT(*) as pending FROM resolution_tracker WHERE resolution_status='PENDING'") as c:
                pending = (await c.fetchone())["pending"]
        accuracy = (correct / resolved) if resolved > 0 else 0.0
        return {
            "total_tracked": total, "resolved": resolved, "pending": pending,
            "correct": correct, "accuracy": round(accuracy, 4),
            "avg_prediction_error": round(avg_err, 4),
        }

    async def get_calibration_report(self) -> dict:
        """
        Generate detailed calibration report with per-category breakdown,
        Brier scores, and overconfidence/underconfidence analysis.
        """
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row

            # Overall stats
            async with db.execute("""
                SELECT COUNT(*) as total,
                       COALESCE(SUM(was_correct), 0) as correct,
                       COALESCE(AVG(prediction_error), 0) as avg_error
                FROM resolution_tracker WHERE resolution_status='RESOLVED'
            """) as c:
                overall = dict(await c.fetchone())

            # Brier score: mean of (predicted - actual)^2
            async with db.execute("""
                SELECT COALESCE(AVG(
                    (our_probability - CASE WHEN resolution_outcome='YES' THEN 1.0 ELSE 0.0 END)
                    * (our_probability - CASE WHEN resolution_outcome='YES' THEN 1.0 ELSE 0.0 END)
                ), 0) as brier_score
                FROM resolution_tracker WHERE resolution_status='RESOLVED'
            """) as c:
                brier = (await c.fetchone())["brier_score"]

            # Per-domain breakdown
            async with db.execute("""
                SELECT domain,
                       COUNT(*) as total,
                       SUM(was_correct) as correct,
                       AVG(prediction_error) as avg_error,
                       AVG((our_probability - CASE WHEN resolution_outcome='YES' THEN 1.0 ELSE 0.0 END)
                           * (our_probability - CASE WHEN resolution_outcome='YES' THEN 1.0 ELSE 0.0 END)
                       ) as brier_score
                FROM resolution_tracker
                WHERE resolution_status='RESOLVED'
                GROUP BY domain
                ORDER BY total DESC
            """) as c:
                categories = [dict(r) for r in await c.fetchall()]

            # Overconfidence analysis: predictions in [0.7, 1.0] that resolved NO,
            # and predictions in [0.0, 0.3] that resolved YES
            async with db.execute("""
                SELECT
                    SUM(CASE WHEN our_probability >= 0.7 AND resolution_outcome='NO' THEN 1 ELSE 0 END) as overconfident_yes,
                    SUM(CASE WHEN our_probability <= 0.3 AND resolution_outcome='YES' THEN 1 ELSE 0 END) as overconfident_no,
                    SUM(CASE WHEN our_probability >= 0.7 THEN 1 ELSE 0 END) as total_high_conf,
                    SUM(CASE WHEN our_probability <= 0.3 THEN 1 ELSE 0 END) as total_low_conf
                FROM resolution_tracker WHERE resolution_status='RESOLVED'
            """) as c:
                conf_data = dict(await c.fetchone())

            # Calibration buckets: group predictions into 10% bands
            async with db.execute("""
                SELECT
                    CAST(our_probability * 10 AS INTEGER) as bucket,
                    COUNT(*) as total,
                    SUM(CASE WHEN resolution_outcome='YES' THEN 1 ELSE 0 END) as actual_yes
                FROM resolution_tracker
                WHERE resolution_status='RESOLVED'
                GROUP BY CAST(our_probability * 10 AS INTEGER)
                ORDER BY bucket
            """) as c:
                buckets = [dict(r) for r in await c.fetchall()]

            # Pending count
            async with db.execute(
                "SELECT COUNT(*) as pending FROM resolution_tracker WHERE resolution_status='PENDING'"
            ) as c:
                pending = (await c.fetchone())["pending"]

        # Process calibration buckets
        calibration_curve = []
        for b in buckets:
            bucket_start = b["bucket"] / 10.0
            bucket_end = bucket_start + 0.1
            predicted_avg = (bucket_start + bucket_end) / 2
            actual_rate = b["actual_yes"] / b["total"] if b["total"] > 0 else 0
            calibration_curve.append({
                "range": f"{bucket_start:.0%}-{bucket_end:.0%}",
                "predicted": round(predicted_avg, 2),
                "actual": round(actual_rate, 4),
                "count": b["total"],
                "gap": round(actual_rate - predicted_avg, 4),
            })

        # Determine bias
        total_high = conf_data.get("total_high_conf") or 0
        total_low = conf_data.get("total_low_conf") or 0
        overconf_yes = conf_data.get("overconfident_yes") or 0
        overconf_no = conf_data.get("overconfident_no") or 0

        if total_high > 0 and (overconf_yes / total_high) > 0.4:
            bias = "overconfident"
        elif total_low > 0 and (overconf_no / total_low) > 0.4:
            bias = "underconfident"
        else:
            bias = "well_calibrated"

        # Best/worst categories
        sorted_cats = sorted(categories, key=lambda x: x.get("brier_score", 1))
        best = sorted_cats[0]["domain"] if sorted_cats else "n/a"
        worst = sorted_cats[-1]["domain"] if sorted_cats else "n/a"

        resolved_total = overall.get("total", 0)
        correct_total = overall.get("correct", 0)

        return {
            "resolved": resolved_total,
            "pending": pending,
            "accuracy": round(correct_total / resolved_total, 4) if resolved_total > 0 else 0,
            "brier_score": round(brier, 4),
            "bias": bias,
            "best_category": best,
            "worst_category": worst,
            "categories": categories,
            "calibration_curve": calibration_curve,
            "overconfidence_data": {
                "high_conf_wrong": overconf_yes,
                "high_conf_total": total_high,
                "low_conf_wrong": overconf_no,
                "low_conf_total": total_low,
            },
        }

    async def save_snapshot(self, snapshot: PortfolioSnapshot):
        """Save a portfolio snapshot."""
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO portfolio_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                str(uuid.uuid4()),
                snapshot.timestamp.isoformat(),
                snapshot.starting_capital,
                snapshot.current_capital,
                snapshot.deployed_capital,
                snapshot.total_pnl,
                snapshot.total_return_pct,
                snapshot.open_positions,
                snapshot.closed_positions,
                snapshot.win_rate,
                snapshot.avg_edge_captured,
                snapshot.phase,
            ))
            await db.commit()
