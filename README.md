# phani-market v2

Polymarket trading bot with clean single-pass calibration, Metaculus comparator, and GDELT news feed.

## Architecture

```
Polymarket API → Research Agent (DeepSeek V3) → Reasoning Agent (DeepSeek R1)
                      ↑                                    ↓
               GDELT News + Metaculus          Single-Pass Platt Calibration
                                                           ↓
                                               Kelly Criterion Sizing
                                                           ↓
                                               Edge Gate (min 4%)
                                                           ↓
                                               Paper Trade Executor → SQLite DB
```

## Setup

### 1. Environment Variables (set in Railway)

```
DEEPSEEK_API_KEY=your_deepseek_api_key
DB_PATH=phani_market.db
PORT=8000
```

### 2. Deploy to Railway

```bash
# Push to GitHub first
git init
git add .
git commit -m "phani-market v2 initial"
git remote add origin YOUR_GITHUB_REPO
git push -u origin main

# Then connect repo to Railway project 818d26ce-f924-4d4b-a533-231dffcd56c6
```

### 3. Local Testing

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY=your_key
python main.py
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| GET /health | Bot status |
| GET /debug | Last scan stats, portfolio value |
| GET /reasoning | Last 5 markets analysed with full chain |
| GET /trades | All paper trades + P&L summary |
| GET /calibration | Brier scores by category |

## Key Settings (settings.py)

| Setting | Value | Description |
|---------|-------|-------------|
| PLATT_SCALE | 0.85 | Single-pass calibration only |
| EDGE_THRESHOLD_BUY | 0.04 | Min 4% edge to bet |
| EDGE_THRESHOLD_STRONG | 0.08 | Strong signal at 8% |
| KELLY_FRACTION | 0.25 | Quarter Kelly (conservative) |
| MAX_POSITION_PCT | 0.05 | Max 5% bankroll per bet |
| METACULUS_GAP_THRESHOLD | 0.10 | Bet when gap > 10% |
| SCAN_INTERVAL_HOURS | 1 | Scan every hour |
| STARTING_BANKROLL | 10000 | Virtual $10,000 |
| PAPER_TRADING | True | Paper trading mode |

## Improvements Over v1

| Problem in v1 | Fix in v2 |
|---------------|-----------|
| Stacked dampeners killing edges | Single-pass Platt scaling only |
| Devil's Advocate double-dipping | Removed entirely |
| No Metaculus comparison | Added — blends when gap > 10% |
| No GDELT news | Added — real-time 3-day context |
| No exit logic | Added — exits when edge < 2% |
| Flat confidence scores | Cleaner R1 prompts with explicit PROBABILITY: output |
| No P&L visibility | SQLite DB with full trade log |

## Calibration

After 2+ weeks of paper trading, check /calibration endpoint for Brier scores.
- Score < 0.10 = excellent
- Score 0.10–0.20 = good
- Score > 0.25 = random (needs tuning)

Use Brier scores to adjust PLATT_SCALE in settings.py.
