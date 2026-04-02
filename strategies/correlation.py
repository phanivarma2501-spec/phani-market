"""
strategies/correlation.py
Detects when open positions share the same underlying theme
and warns before adding correlated bets.
"""

import re
from typing import List, Dict, Tuple, Optional
from loguru import logger

# Theme keywords — a position's question is checked against these
# to assign one or more themes. Two positions sharing a theme are correlated.
THEME_KEYWORDS = {
    # Geopolitical themes
    "us_iran": ["iran", "tehran", "khamenei", "rouhani", "persian gulf", "strait of hormuz", "us-iran", "us x iran"],
    "ukraine_russia": ["ukraine", "russia", "putin", "zelensky", "crimea", "donbas", "nato expansion"],
    "china_taiwan": ["china", "taiwan", "xi jinping", "strait", "pla", "ccp"],
    "israel_palestine": ["israel", "gaza", "hamas", "netanyahu", "west bank", "hezbollah"],
    "us_elections": ["trump", "biden", "democrat", "republican", "2024 election", "2026 election", "midterm", "gop", "dnc"],
    "european_politics": ["eu", "european union", "macron", "scholz", "orban", "hungary", "parliament"],

    # Crypto themes
    "bitcoin_price": ["bitcoin", "btc", "bitcoin price", "btc price"],
    "ethereum_price": ["ethereum", "eth", "eth price"],
    "crypto_regulation": ["sec crypto", "cftc", "crypto regulation", "crypto ban", "stablecoin"],
    "defi": ["defi", "decentralized finance", "tvl", "yield"],

    # Economic themes
    "fed_policy": ["fed", "fomc", "interest rate", "rate cut", "rate hike", "powell", "federal reserve"],
    "inflation": ["inflation", "cpi", "pce", "consumer price"],
    "recession": ["recession", "gdp", "economic contraction", "downturn"],
    "oil_energy": ["oil", "crude", "opec", "energy", "brent", "wti", "natural gas"],

    # Corporate/sector themes
    "tech_sector": ["apple", "google", "meta", "microsoft", "nvidia", "ai", "artificial intelligence"],
    "banking": ["bank", "svb", "banking crisis", "credit", "fdic"],
}


def detect_themes(question: str) -> List[str]:
    """Extract all matching themes from a market question."""
    question_lower = question.lower()
    themes = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in question_lower for kw in keywords):
            themes.append(theme)
    return themes


def find_correlations(
    open_positions: List[Dict],
    new_question: str,
) -> List[Dict]:
    """
    Check if a new market correlates with any open positions.
    Returns a list of correlation warnings.

    Each open position dict should have at least:
        market_condition_id, market_question, size_usd, domain
    """
    new_themes = detect_themes(new_question)
    if not new_themes:
        return []

    warnings = []
    theme_positions: Dict[str, List[Dict]] = {}

    # Group existing positions by theme
    for pos in open_positions:
        pos_themes = detect_themes(pos.get("market_question", ""))
        for theme in pos_themes:
            if theme not in theme_positions:
                theme_positions[theme] = []
            theme_positions[theme].append(pos)

    # Check overlap with new market
    for theme in new_themes:
        if theme in theme_positions:
            correlated = theme_positions[theme]
            total_exposure = sum(p.get("size_usd", 0) for p in correlated)
            warnings.append({
                "theme": theme,
                "correlated_positions": len(correlated),
                "total_exposure_usd": round(total_exposure, 2),
                "correlated_markets": [
                    p.get("market_question", "")[:60] for p in correlated
                ],
            })

    return warnings


def format_correlation_warning(warnings: List[Dict], new_question: str) -> str:
    """Format correlation warnings as a human-readable string."""
    if not warnings:
        return ""

    lines = [f"CORRELATION WARNING for: {new_question[:60]}"]
    for w in warnings:
        lines.append(
            f"  Theme '{w['theme']}': {w['correlated_positions']} existing position(s), "
            f"${w['total_exposure_usd']:.2f} already deployed"
        )
        for mkt in w["correlated_markets"]:
            lines.append(f"    - {mkt}")

    return "\n".join(lines)


class CorrelationDetector:
    """
    Stateful correlation detector that integrates with the paper trader.
    Call check_before_trade() before opening a new position.
    """

    def __init__(self, max_correlated_positions: int = 3, max_theme_exposure_pct: float = 0.20):
        self.max_correlated_positions = max_correlated_positions
        self.max_theme_exposure_pct = max_theme_exposure_pct

    def check_before_trade(
        self,
        open_positions: List[Dict],
        new_question: str,
        new_size_usd: float,
        total_capital: float,
    ) -> Tuple[bool, str]:
        """
        Check if a new trade would create excessive correlation.

        Returns:
            (should_proceed, reason)
            - (True, "") if safe to trade
            - (False, "reason") if trade should be blocked/reduced
        """
        warnings = find_correlations(open_positions, new_question)
        if not warnings:
            return True, ""

        for w in warnings:
            # Check 1: Too many positions in same theme
            if w["correlated_positions"] >= self.max_correlated_positions:
                reason = (
                    f"BLOCKED: Theme '{w['theme']}' already has {w['correlated_positions']} positions "
                    f"(max {self.max_correlated_positions}). "
                    f"Existing exposure: ${w['total_exposure_usd']:.2f}"
                )
                logger.warning(reason)
                return False, reason

            # Check 2: Theme exposure too high as % of capital
            new_exposure = w["total_exposure_usd"] + new_size_usd
            exposure_pct = new_exposure / total_capital if total_capital > 0 else 1.0
            if exposure_pct > self.max_theme_exposure_pct:
                reason = (
                    f"BLOCKED: Theme '{w['theme']}' would reach {exposure_pct:.1%} of capital "
                    f"(max {self.max_theme_exposure_pct:.0%}). "
                    f"Current: ${w['total_exposure_usd']:.2f} + new ${new_size_usd:.2f}"
                )
                logger.warning(reason)
                return False, reason

        # Warn but allow if under limits
        warning_text = format_correlation_warning(warnings, new_question)
        logger.info(f"Correlation noted (within limits):\n{warning_text}")
        return True, warning_text
