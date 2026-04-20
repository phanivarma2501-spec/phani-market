import os

# ─── LLM ───────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
RESEARCH_MODEL = "deepseek-chat"       # DeepSeek V3
REASONING_MODEL = "deepseek-reasoner"  # DeepSeek R1

# ─── Calibration ───────────────────────────────────────────────────────────
PLATT_SCALE = 0.85          # Single-pass only — no stacking

# ─── Edge Gates ────────────────────────────────────────────────────────────
EDGE_THRESHOLD_BUY = 0.05   # 5% minimum edge to place bet (longshots caught by MIN_ENTRY_PRICE)
EDGE_THRESHOLD_STRONG = 0.08 # 8% = strong signal
MIN_ENTRY_PRICE = 0.05      # Skip longshots: no bets where entry price < 5%
MAX_OPEN_POSITIONS = 7      # Hard cap on concurrent open positions
REENTRY_COOLDOWN_HOURS = 24 # Don't re-enter a market within N hours of any prior trade
EXCLUDED_CATEGORIES = ["gaming", "esports", "entertainment", "tv", "celebrity", "reality"]
# Sports games are filtered separately via Polymarket's sportsMarketType field.
# The above categories are matched against question text keywords in polymarket.py
# because the Gamma API's `category` field is almost always null.

# ─── Kelly Criterion ───────────────────────────────────────────────────────
KELLY_FRACTION = 0.25        # Quarter Kelly — conservative
MAX_POSITION_PCT = 0.05      # Max 5% of bankroll per bet
MIN_POSITION_USD = 5.0       # Minimum bet size

# ─── Metaculus ─────────────────────────────────────────────────────────────
METACULUS_ENABLED = os.environ.get("METACULUS_ENABLED", "false").lower() == "true"
METACULUS_API_TOKEN = os.environ.get("METACULUS_API_TOKEN", "")
METACULUS_GAP_THRESHOLD = 0.10       # Blend when |metaculus - calibrated| > this
METACULUS_MATCH_THRESHOLD = 0.35     # Jaccard similarity floor to accept a match
METACULUS_BASE_URL = "https://www.metaculus.com/api2"

# ─── GDELT ─────────────────────────────────────────────────────────────────
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# ─── Polymarket ────────────────────────────────────────────────────────────
POLYMARKET_BASE_URL = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
MIN_LIQUIDITY_USD = 1000     # Skip illiquid markets
MAX_MARKETS_PER_SCAN = 25

# ─── Paper Trading ─────────────────────────────────────────────────────────
PAPER_TRADING = True
STARTING_BANKROLL = 10000.0  # Virtual $10,000

# ─── Exit Logic ────────────────────────────────────────────────────────────
EXIT_EDGE_THRESHOLD = 0.02        # Exit position when edge drops below 2%
PRICE_REFRESH_THRESHOLD = 0.10    # Re-run research + reasoning on open positions when |current - entry| > this

# ─── Scheduler ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_HOURS = 1      # Scan every 1 hour

# ─── API ───────────────────────────────────────────────────────────────────
API_PORT = int(os.environ.get("PORT", 8000))
