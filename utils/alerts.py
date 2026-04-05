"""
utils/alerts.py
Telegram alerts for signals, resolved trades, and daily summaries.
All alerts are informational — Phase 1 never executes real trades.
"""

import httpx
from typing import Optional
from loguru import logger

from core.models import ReasoningResult, SignalStrength, PortfolioSnapshot, BotAlert
from config.settings import settings

# Signal emoji map
SIGNAL_EMOJI = {
    SignalStrength.STRONG_BUY: "🟢🟢",
    SignalStrength.BUY: "🟢",
    SignalStrength.HOLD: "⚪",
    SignalStrength.SELL: "🔴",
    SignalStrength.STRONG_SELL: "🔴🔴",
}


class TelegramAlerter:
    """Sends Telegram messages for key bot events."""

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.info("Telegram alerts disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable")

    async def send(self, text: str) -> bool:
        """Send a raw Telegram message."""
        if not self.enabled:
            logger.info(f"[ALERT] {text[:100]}")
            return True
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def signal_alert(self, result: ReasoningResult) -> bool:
        """Alert for a new BUY/SELL signal."""
        emoji = SIGNAL_EMOJI.get(result.signal, "⚪")
        direction = "YES" if result.signal in {SignalStrength.BUY, SignalStrength.STRONG_BUY} else "NO"

        msg = (
            f"{emoji} <b>PAPER SIGNAL — {result.signal.value}</b>\n\n"
            f"<b>Market:</b> {result.market_question[:100]}\n\n"
            f"<b>Our P:</b> {result.our_probability:.1%}  |  "
            f"<b>Market P:</b> {result.market_probability:.1%}\n"
            f"<b>Edge:</b> {result.edge:+.1%}  |  "
            f"<b>Confidence:</b> {result.confidence:.0%}\n"
            f"<b>Direction:</b> {direction}\n"
            f"<b>Suggested size:</b> ${result.suggested_position_usd:.2f} "
            f"({result.suggested_position_pct:.1%} of capital)\n\n"
            f"<i>Phase 1 — paper trade only. No real money deployed.</i>"
        )
        return await self.send(msg)

    async def trade_closed_alert(
        self,
        market_question: str,
        won: bool,
        pnl_usd: float,
        pnl_pct: float,
    ) -> bool:
        """Alert when a paper trade resolves."""
        result_emoji = "✅" if won else "❌"
        msg = (
            f"{result_emoji} <b>PAPER TRADE RESOLVED — {'WIN' if won else 'LOSS'}</b>\n\n"
            f"<b>Market:</b> {market_question[:100]}\n"
            f"<b>P&L:</b> ${pnl_usd:+.2f} ({pnl_pct:+.1%})\n"
        )
        return await self.send(msg)

    async def daily_summary_alert(self, snapshot: PortfolioSnapshot) -> bool:
        """Daily portfolio performance summary."""
        trend = "📈" if snapshot.total_pnl >= 0 else "📉"
        msg = (
            f"{trend} <b>Daily Summary — Phase {snapshot.phase}</b>\n\n"
            f"<b>Capital:</b> ${snapshot.current_capital:,.2f}\n"
            f"<b>Total return:</b> {snapshot.total_return_pct:+.1%}\n"
            f"<b>P&L:</b> ${snapshot.total_pnl:+,.2f}\n\n"
            f"<b>Open positions:</b> {snapshot.open_positions}\n"
            f"<b>Closed positions:</b> {snapshot.closed_positions}\n"
            f"<b>Win rate:</b> {snapshot.win_rate:.0%}\n"
            f"<b>Avg edge on wins:</b> {snapshot.avg_edge_captured:.1%}\n\n"
            f"<i>All trades are paper — no real money deployed.</i>"
        )
        return await self.send(msg)

    async def error_alert(self, error: str) -> bool:
        """Alert for critical errors."""
        msg = f"⚠️ <b>Bot Error</b>\n\n<code>{error[:500]}</code>"
        return await self.send(msg)

    async def startup_alert(self) -> bool:
        """Alert when bot starts."""
        msg = (
            f"🤖 <b>Polymarket Bot Started</b>\n\n"
            f"<b>Phase:</b> {settings.PHASE} (Paper trading only)\n"
            f"<b>Domains:</b> {', '.join(settings.FOCUS_DOMAINS)}\n"
            f"<b>Min edge:</b> {settings.MIN_EDGE_TO_FLAG:.0%}\n"
            f"<b>Min confidence:</b> {settings.REASONING_CONFIDENCE_MIN:.0%}\n\n"
            f"<i>Monitoring markets. No real capital at risk.</i>"
        )
        return await self.send(msg)

    async def weekly_calibration_alert(self, report: dict) -> bool:
        """Send weekly calibration report to Telegram."""
        resolved = report.get("resolved", 0)
        if resolved == 0:
            msg = (
                "📊 <b>Weekly Calibration Report</b>\n\n"
                "No markets resolved yet. Report will populate as markets close."
            )
            return await self.send(msg)

        accuracy = report.get("accuracy", 0)
        brier = report.get("brier_score", 0)
        bias = report.get("bias", "unknown")
        pending = report.get("pending", 0)
        best = report.get("best_category", "n/a")
        worst = report.get("worst_category", "n/a")

        # Bias emoji
        bias_map = {
            "overconfident": "🔴 Overconfident",
            "underconfident": "🟡 Underconfident",
            "well_calibrated": "🟢 Well Calibrated",
        }
        bias_str = bias_map.get(bias, bias)

        # Category breakdown
        cat_lines = []
        for cat in report.get("categories", []):
            domain = cat.get("domain", "?")
            cat_total = cat.get("total", 0)
            cat_correct = cat.get("correct", 0)
            cat_brier = cat.get("brier_score", 0)
            cat_acc = cat_correct / cat_total if cat_total > 0 else 0
            cat_lines.append(
                f"  {domain}: {cat_acc:.0%} accuracy ({cat_total} resolved, Brier: {cat_brier:.3f})"
            )
        cat_text = "\n".join(cat_lines) if cat_lines else "  No category data yet"

        # Calibration curve summary
        curve_lines = []
        for bucket in report.get("calibration_curve", []):
            predicted = bucket.get("predicted", 0)
            actual = bucket.get("actual", 0)
            count = bucket.get("count", 0)
            gap = bucket.get("gap", 0)
            arrow = "↑" if gap > 0.05 else "↓" if gap < -0.05 else "≈"
            curve_lines.append(
                f"  {bucket['range']}: predicted {predicted:.0%} → actual {actual:.0%} {arrow} (n={count})"
            )
        curve_text = "\n".join(curve_lines) if curve_lines else "  Insufficient data"

        # Overconfidence detail
        oc = report.get("overconfidence_data", {})
        oc_text = (
            f"  High-conf wrong: {oc.get('high_conf_wrong', 0)}/{oc.get('high_conf_total', 0)}\n"
            f"  Low-conf wrong: {oc.get('low_conf_wrong', 0)}/{oc.get('low_conf_total', 0)}"
        )

        msg = (
            f"📊 <b>Weekly Calibration Report</b>\n\n"
            f"<b>Overall:</b> {accuracy:.1%} accuracy | Brier: {brier:.3f}\n"
            f"<b>Bias:</b> {bias_str}\n"
            f"<b>Resolved:</b> {resolved} | <b>Pending:</b> {pending}\n\n"
            f"<b>Best category:</b> {best}\n"
            f"<b>Worst category:</b> {worst}\n\n"
            f"<b>By Category:</b>\n<pre>{cat_text}</pre>\n\n"
            f"<b>Calibration Curve:</b>\n<pre>{curve_text}</pre>\n\n"
            f"<b>Confidence Analysis:</b>\n<pre>{oc_text}</pre>\n\n"
            f"<i>Lower Brier = better. Perfect = 0.0, random = 0.25</i>"
        )
        return await self.send(msg)
