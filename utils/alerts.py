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
