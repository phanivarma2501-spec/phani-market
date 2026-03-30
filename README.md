# Polymarket Research Bot — Phase 1

AI-powered prediction market research bot using Claude's structured reasoning engine.

**Phase 1 = Paper trading only. Zero real capital at risk.**

---

## What makes this different

Every other Polymarket bot asks an LLM "what's the probability?" and takes the raw answer.

This bot uses **Tetlock superforecasting methodology** in 6 structured steps:
1. Reference class selection
2. Base rate anchoring
3. Inside view (case-specific factors)
4. Outside view (systemic adjustments)
5. News adjustment (real-time)
6. Synthesis + confidence banding

Then applies **Platt scaling** to recalibrate LLM overconfidence, and **fractional Kelly sizing** with confidence bands to determine position size.

---

## Architecture

```
main.py                    ← CLI entry point
├── core/
│   ├── engine.py          ← Main orchestration loop
│   ├── market_fetcher.py  ← Gamma API + domain filter
│   └── models.py          ← Pydantic data models
├── data/
│   ├── news_fetcher.py    ← RSS + Google News per market
│   └── storage.py         ← SQLite async storage
├── reasoning/
│   └── superforecaster.py ← 6-step Claude reasoning engine ← THE EDGE
├── strategies/
│   └── paper_trader.py    ← Paper trade engine + Kelly sizing
├── utils/
│   └── alerts.py          ← Telegram notifications
└── config/
    └── settings.py        ← All configuration
```

---

## Quick start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY (required)
# Add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (optional but recommended)
```

### 3. Test market fetching (free — no API calls)
```bash
PYTHONPATH=. python main.py test
```

### 4. Run a single reasoning cycle
```bash
PYTHONPATH=. python main.py once
```

### 5. Run the full bot
```bash
PYTHONPATH=. python main.py run
```

### 6. Check paper portfolio status
```bash
PYTHONPATH=. python main.py status
```

---

## Phase roadmap

| Phase | What | When to advance |
|-------|------|-----------------|
| **Phase 1** | Paper trading only — validate reasoning engine | After 60+ days, win rate > 58%, positive edge |
| **Phase 2** | Live trading with small capital ($200–$500) | After Phase 1 validates |
| **Phase 3** | Scaled live trading with human approval gate | After Phase 2 profitable |

**Never skip phases. 70% of Polymarket traders lose money.**

---

## Configuration

Key settings in `.env` or `config/settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `FOCUS_DOMAINS` | `["crypto","politics","economics"]` | Markets to analyse |
| `MIN_EDGE_TO_FLAG` | `0.06` | Minimum edge (6%) to trigger signal |
| `HIGH_CONFIDENCE_EDGE` | `0.12` | Strong signal threshold (12%) |
| `REASONING_CONFIDENCE_MIN` | `0.65` | Drop signals below 65% confidence |
| `MAX_POSITION_PCT` | `0.05` | Max 5% of capital per market |
| `KELLY_FRACTION` | `0.25` | Fractional Kelly (25% of full Kelly) |

---

## How signals work

```
Market qualifies (domain + liquidity + volume + timing + probability band)
    → News fetched (RSS + Google News, scored by relevance)
    → 6-step superforecasting (Claude reasoning)
    → Platt scaling calibration (compresses overconfidence)
    → Edge calculation: our_probability − market_probability
    → Confidence banding: confidence < 0.65 → HOLD
    → Kelly sizing: fractional Kelly × confidence scaler
    → Signal: STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL
    → Paper trade recorded (Phase 1) / Telegram alert sent
```

---

## Running tests

```bash
PYTHONPATH=. python tests/test_bot.py
```

All 9 tests should pass. Tests cover:
- Platt scaling calibration
- Signal threshold logic
- Kelly position sizing
- Market domain classification
- Market filter logic
- Paper trader (open/hold/duplicate)
- Storage round-trip
- Portfolio performance stats

---

## Telegram setup

1. Message `@BotFather` on Telegram → `/newbot` → get token
2. Message `@userinfobot` → get your chat ID
3. Add both to `.env`

You'll receive alerts for every BUY/SELL signal and a daily summary.

---

## Key numbers from the data

- Only **7.6%** of Polymarket traders are profitable
- **70%** of retail traders lose money
- Top reasoning-based bots achieve **62–78%** win rate
- Our target: **55–70%** win rate in Year 1 (paper → live)
- Minimum edge to signal: **6%** (our probability − market probability)

---

## Important warnings

- This is **experimental software** — no guarantees of profitability
- `LIVE_TRADING_ENABLED` is hardcoded `False` in Phase 1
- Never run Phase 2/3 without reviewing the full reasoning output first
- Polymarket has no stop-losses, no circuit breakers — size positions conservatively
- Past performance of documented bots does not guarantee future results
