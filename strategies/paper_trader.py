"""
strategies/paper_trader.py
Paper trading engine — Phase 1 only. Records simulated trades,
tracks performance, validates the reasoning engine before any
real capital is ever deployed.

This is the validation layer. If this doesn't show consistent
positive edge over 2 months, we never move to Phase 2.
"""

import uuid
from datetime import datetime
from typing import List, Optional
from loguru import logger

from core.models import (
    ReasoningResult, PaperTrade, PortfolioSnapshot,
    SignalStrength, Domain
)
from data.storage import Storage
from config.settings import settings


# Signals that warrant opening a paper position
ACTIONABLE_SIGNALS = {SignalStrength.BUY, SignalStrength.STRONG_BUY,
                      SignalStrength.SELL, SignalStrength.STRONG_SELL}


class PaperTrader:
    """
    Converts reasoning signals into paper trades and tracks performance.

    Phase 1 rules:
    - NEVER executes real orders
    - Records every signal with full metadata
    - Calculates live P&L as markets resolve
    - Enforces position limits (max 5% per market, 15% correlated)
    - Generates daily performance reports
    """

    def __init__(
        self,
        storage: Storage,
        starting_capital: float = 10_000.0
    ):
        self.storage = storage
        self.starting_capital = starting_capital
        self.current_capital = starting_capital
        self._open_trades: List[dict] = []

    async def load_state(self):
        """Reload open positions from DB on startup."""
        self._open_trades = await self.storage.get_open_trades()
        logger.info(f"Loaded {len(self._open_trades)} open paper positions")

    def _is_duplicate_position(self, market_condition_id: str) -> bool:
        """Check if we already have an open position in this market."""
        return any(
            t["market_condition_id"] == market_condition_id
            for t in self._open_trades
        )

    def _current_exposure_pct(self) -> float:
        """Total capital currently deployed as a percentage."""
        deployed = sum(t.get("size_usd", 0) for t in self._open_trades)
        return deployed / self.current_capital if self.current_capital > 0 else 0.0

    def _correlated_exposure(self, domain: Domain) -> float:
        """Exposure in markets of the same domain (correlation proxy)."""
        domain_deployed = sum(
            t.get("size_usd", 0) for t in self._open_trades
            if t.get("domain") == domain.value
        )
        return domain_deployed / self.current_capital if self.current_capital > 0 else 0.0

    def _calculate_position_size(
        self,
        result: ReasoningResult,
        signal: SignalStrength,
    ) -> float:
        """
        Determine position size respecting all risk limits.
        Returns USD amount to deploy (0 if limits exceeded).
        """
        # Hard check: never exceed total exposure limit
        if self._current_exposure_pct() >= 1.00:
            logger.warning("Total exposure at 100% limit — skipping position")
            return 0.0

        # Domain correlation check
        if self._correlated_exposure(Domain.CRYPTO) >= settings.MAX_CORRELATED_EXPOSURE:
            if "crypto" in result.market_question.lower():
                logger.warning("Crypto exposure at limit — skipping")
                return 0.0

        # Use Kelly-suggested size, but scale by signal strength
        base_size = result.suggested_position_usd
        if signal == SignalStrength.STRONG_BUY or signal == SignalStrength.STRONG_SELL:
            size = base_size * 1.25  # Up to 125% of Kelly for strong signals
        else:
            size = base_size

        # Cap at max position size
        max_size = self.current_capital * settings.MAX_POSITION_PCT
        return round(min(size, max_size), 2)

    async def process_signal(
        self, result: ReasoningResult
    ) -> Optional[PaperTrade]:
        """
        Process a reasoning result and open a paper trade if warranted.
        Returns the PaperTrade if opened, None otherwise.
        """
        # Only act on actionable signals
        if result.signal not in ACTIONABLE_SIGNALS:
            logger.debug(
                f"HOLD signal for '{result.market_question[:40]}' "
                f"(edge={result.edge:+.1%}, conf={result.confidence:.0%})"
            )
            return None

        # No duplicate positions
        if self._is_duplicate_position(result.market_condition_id):
            logger.debug(f"Already have position in {result.market_condition_id[:12]}...")
            return None

        # Determine trade direction
        is_buy = result.signal in {SignalStrength.BUY, SignalStrength.STRONG_BUY}
        side = "YES" if is_buy else "NO"
        entry_price = result.market_probability if is_buy else (1.0 - result.market_probability)

        # Calculate size
        size_usd = self._calculate_position_size(result, result.signal)
        if size_usd < 5.0:  # Minimum trade size
            logger.debug(f"Position size ${size_usd:.2f} below minimum — skipping")
            return None

        # Create the paper trade
        trade = PaperTrade(
            id=str(uuid.uuid4()),
            market_condition_id=result.market_condition_id,
            market_question=result.market_question,
            side=side,
            entry_price=entry_price,
            size_usd=size_usd,
            signal=result.signal,
            our_probability=result.our_probability,
            market_probability=result.market_probability,
            edge=result.edge,
            confidence=result.confidence,
            domain=Domain.OTHER,  # Will be enriched by caller
        )

        # Save to DB and memory
        trade.id = await self.storage.save_paper_trade(trade)
        self._open_trades.append({
            "market_condition_id": trade.market_condition_id,
            "size_usd": trade.size_usd,
            "domain": trade.domain.value,
            "id": trade.id,
        })

        logger.info(
            f"PAPER TRADE OPENED: {side} '{result.market_question[:50]}' | "
            f"${size_usd:.2f} @ {entry_price:.2f} | "
            f"Edge: {result.edge:+.1%} | Conf: {result.confidence:.0%} | "
            f"Signal: {result.signal.value}"
        )
        return trade

    async def close_trade(
        self,
        trade_id: str,
        market_condition_id: str,
        resolution: str,  # "YES" or "NO"
        market_question: str,
    ) -> Optional[dict]:
        """
        Close a paper trade when a market resolves.
        Calculates P&L and updates portfolio.
        """
        open_trades = await self.storage.get_open_trades()
        trade_row = next(
            (t for t in open_trades if t["id"] == trade_id), None
        )
        if not trade_row:
            return None

        side = trade_row["side"]
        entry_price = trade_row["entry_price"]
        size_usd = trade_row["size_usd"]

        # Calculate P&L
        won = (side == resolution)
        if won:
            # Received $1 per share. Shares = size_usd / entry_price
            shares = size_usd / entry_price
            proceeds = shares * 1.0
            # Polymarket 2% winner fee
            fee = proceeds * 0.02
            pnl_usd = proceeds - fee - size_usd
        else:
            # Lost the entire position
            pnl_usd = -size_usd

        pnl_pct = pnl_usd / size_usd if size_usd > 0 else 0.0

        # Update capital
        self.current_capital += pnl_usd

        # Remove from open positions
        self._open_trades = [
            t for t in self._open_trades
            if t.get("id") != trade_id
        ]

        result = {
            "trade_id": trade_id,
            "market_question": market_question,
            "side": side,
            "resolution": resolution,
            "won": won,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 4),
            "exit_price": 1.0 if won else 0.0,
        }

        logger.info(
            f"PAPER TRADE CLOSED: {'WIN' if won else 'LOSS'} | "
            f"'{market_question[:40]}' | "
            f"P&L: ${pnl_usd:+.2f} ({pnl_pct:+.1%})"
        )
        return result

    async def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Generate current portfolio state."""
        perf = await self.storage.get_performance_summary()
        return PortfolioSnapshot(
            starting_capital=self.starting_capital,
            current_capital=self.current_capital,
            deployed_capital=perf["deployed_capital"],
            total_pnl=perf["total_pnl_usd"],
            total_return_pct=(self.current_capital - self.starting_capital) / self.starting_capital,
            open_positions=perf["open_trades"],
            closed_positions=perf["closed_trades"],
            win_rate=perf["win_rate"],
            avg_edge_captured=perf["avg_edge_on_wins"],
            phase=settings.PHASE,
        )

    def format_summary(self, snapshot: PortfolioSnapshot) -> str:
        """Format portfolio summary for logging/alerts."""
        return (
            f"Portfolio: ${snapshot.current_capital:,.2f} "
            f"({snapshot.total_return_pct:+.1%} return) | "
            f"Open: {snapshot.open_positions} | "
            f"Closed: {snapshot.closed_positions} | "
            f"Win rate: {snapshot.win_rate:.0%} | "
            f"P&L: ${snapshot.total_pnl:+,.2f}"
        )
