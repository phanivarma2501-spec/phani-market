# Polymarket Bot — VS Code Extension

## Installation (2 ways)

### Option A — Install .vsix directly (easiest)
1. Open VS Code
2. Press `Ctrl+Shift+P` → type `Extensions: Install from VSIX`
3. Select `polymarket-bot-1.0.0.vsix`
4. Reload VS Code when prompted

### Option B — Load as development extension
1. Copy the `polymarket-vscode/` folder anywhere on your machine
2. Open VS Code → `File → Open Folder` → select `polymarket-vscode/`
3. Press `F5` to launch Extension Development Host
4. A new VS Code window opens with the extension active

---

## Setup after install

### 1. Set your API key
`Ctrl+,` → search "polymarket" → enter your **Anthropic API key**

Or open Command Palette → `Polymarket: Configure Bot Settings`

### 2. Set bot path
In settings, set `polymarket.botPath` to the folder where you downloaded `polymarket_bot/`

Example: `/Users/phani/polymarket_bot`

### 3. Open the dashboard
- Click the hexagon icon in the Activity Bar (left sidebar)
- Or press `Ctrl+Alt+M` (Mac: `Cmd+Alt+M`)
- Or Command Palette → `Polymarket: Open Full Dashboard`

---

## What you'll see

### Activity Bar (left sidebar)
- **Live Signals** — latest BUY/SELL signals, compact view
- **Paper Portfolio** — capital, P&L, win rate
- **Reasoning Chain** — last superforecasting output
- **Qualified Markets** — markets currently being tracked

### Full Dashboard (`Ctrl+Alt+M`)
- Complete signal table with edge/confidence/suggested size
- Clickable rows → shows 6-step reasoning chain
- Portfolio metrics
- Qualified markets list

### Status Bar (bottom right)
- `⬡ Poly: Idle` — bot ready
- `⬡ Poly: Scanning` — running a cycle
- `⬡ Poly: Signal!` — new signals found

---

## Commands (Command Palette)

| Command | What it does |
|---------|-------------|
| `Polymarket: Run Market Scan` | Full scan + reasoning cycle |
| `Polymarket: Open Full Dashboard` | Open the main dashboard |
| `Polymarket: Show Portfolio Status` | Update portfolio stats |
| `Polymarket: Configure Bot Settings` | Open settings |
| `Polymarket: Stop Bot` | Stop any running process |

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Alt+M` | Open dashboard |

---

## Settings reference

| Setting | Default | Description |
|---------|---------|-------------|
| `polymarket.anthropicApiKey` | — | Required: Anthropic API key |
| `polymarket.telegramBotToken` | — | Optional: Telegram alerts |
| `polymarket.telegramChatId` | — | Optional: Telegram chat ID |
| `polymarket.focusDomains` | `["crypto","politics","economics"]` | Domains to analyse |
| `polymarket.minEdge` | `0.06` | Minimum 6% edge to flag |
| `polymarket.minConfidence` | `0.65` | Minimum 65% confidence |
| `polymarket.startingCapital` | `10000` | Paper capital in USD |
| `polymarket.botPath` | auto | Path to `polymarket_bot/` |
| `polymarket.autoStartOnOpen` | `false` | Auto-scan on VS Code open |

---

## Demo mode
The dashboard loads with demo signals immediately so you can see the UI before running a real scan. Click any signal row to see the full 6-step reasoning chain.
