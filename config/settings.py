"""
config/settings.py
Central configuration for the Polymarket Phase 1 bot.
Phase 1 = PAPER TRADING ONLY. No live trades executed.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


class PolymarketConfig(BaseSettings):
    # --- API endpoints (public, no auth needed for Phase 1 read-only) ---
    GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
    CLOB_API_URL: str = "https://clob.polymarket.com"
    DATA_API_URL: str = "https://data-api.polymarket.com"

    # --- Gemini (for reasoning engine) ---
    GEMINI_API_KEY: str = Field(default="", env="GEMINI_API_KEY")

    # --- Telegram alerts ---
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(None, env="TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = Field(None, env="TELEGRAM_CHAT_ID")

    # --- Phase control ---
    PHASE: int = 1           # 1=paper only, 2=paper+live small, 3=live full
    PAPER_TRADING: bool = True   # NEVER set False in Phase 1
    LIVE_TRADING_ENABLED: bool = False  # Hard override — requires explicit Phase 3

    # --- Domain specialisation ---
    # Only analyse markets in these categories (our edge)
    FOCUS_DOMAINS: List[str] = [
        "crypto",
        "politics",
        "economics",
    ]
    # Keywords that must appear in market question for it to qualify
    DOMAIN_KEYWORDS: dict = {
        "politics": ["election", "president", "minister", "government", "vote",
                     "congress", "senate", "parliament", "modi", "trump", "policy",
                     "war", "ceasefire", "military", "invasion", "iran", "nato",
                     "netanyahu", "putin", "zelensky", "democrat", "republican",
                     "tariff", "sanction", "coalition", "prime minister", "israel",
                     "china", "russia", "ukraine", "nuclear", "missile"],
        "economics": ["gdp", "inflation", "fed", "interest rate", "recession",
                      "unemployment", "rbi", "rba", "ecb", "cpi", "ppi", "nfp",
                      "stock market", "s&p", "nasdaq", "dow jones", "treasury",
                      "bond", "yield curve", "jobs report", "trade deficit"],
        "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "sol", "solana",
                   "defi", "token", "blockchain", "polygon", "matic", "altcoin",
                   "stablecoin", "nft", "web3", "binance", "coinbase"],
    }

    # --- Market filters ---
    MIN_LIQUIDITY_USD: float = 5_000     # Ignore illiquid markets
    MIN_VOLUME_24H: float = 1_000        # Need active trading
    MAX_DAYS_TO_RESOLUTION: int = 90     # Don't touch ultra-long-dated
    MIN_DAYS_TO_RESOLUTION: int = 1      # Avoid already-resolved
    PROBABILITY_BAND_MIN: float = 0.08   # Skip near-certainties
    PROBABILITY_BAND_MAX: float = 0.92   # Skip near-certainties

    # --- Reasoning thresholds ---
    MIN_EDGE_TO_FLAG: float = 0.06       # Only flag if our P - market P >= 6%
    HIGH_CONFIDENCE_EDGE: float = 0.12   # "Strong signal" threshold
    REASONING_CONFIDENCE_MIN: float = 0.65  # Drop signals below this confidence

    # --- Kelly sizing (Phase 2+ only, calculated now for reference) ---
    KELLY_FRACTION: float = 0.25         # Fractional Kelly (never full Kelly)
    MAX_POSITION_PCT: float = 0.05       # Max 5% of capital per market
    MAX_CORRELATED_EXPOSURE: float = 0.15  # Max 15% in correlated markets

    # --- Scan schedule ---
    MARKET_SCAN_INTERVAL_MINUTES: int = 60   # How often to scan for new markets
    REASONING_SCAN_INTERVAL_MINUTES: int = 60  # How often to re-reason existing
    NEWS_FETCH_INTERVAL_MINUTES: int = 10

    # --- Storage ---
    DB_PATH: str = "/app/data/polymarket_bot.db" if os.environ.get("RAILWAY_ENVIRONMENT") else str(BASE_DIR / "data" / "polymarket_bot.db")
    LOG_PATH: str = str(BASE_DIR / "logs" / "bot.log")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Singleton
settings = PolymarketConfig()
