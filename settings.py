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
MAX_OPEN_POSITIONS = 5      # Hard cap on concurrent open positions
EXCLUDED_CATEGORIES = ["sports", "gaming", "esports"]  # Skip these market categories entirely

# ─── Kelly Criterion ───────────────────────────────────────────────────────
KELLY_FRACTION = 0.25        # Quarter Kelly — conservative
MAX_POSITION_PCT = 0.05      # Max 5% of bankroll per bet
MIN_POSITION_USD = 5.0       # Minimum bet size

# ─── Metaculus ─────────────────────────────────────────────────────────────
METACULUS_GAP_THRESHOLD = 0.10   # Bet when gap > 10%
METACULUS_BASE_URL = "https://www.metaculus.com/api2"

# ─── GDELT ─────────────────────────────────────────────────────────────────
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# ─── Polymarket ────────────────────────────────────────────────────────────
POLYMARKET_BASE_URL = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
MIN_LIQUIDITY_USD = 1000     # Skip illiquid markets
MAX_MARKETS_PER_SCAN = 10

# ─── Paper Trading ─────────────────────────────────────────────────────────
PAPER_TRADING = True
STARTING_BANKROLL = 10000.0  # Virtual $10,000

# ─── Exit Logic ────────────────────────────────────────────────────────────
EXIT_EDGE_THRESHOLD = 0.02   # Exit position when edge drops below 2%

# ─── Scheduler ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_HOURS = 1      # Scan every 1 hour

# ─── API ───────────────────────────────────────────────────────────────────
API_PORT = int(os.environ.get("PORT", 8000))
