"""
web/app.py - FastAPI dashboard for Polymarket Paper Trading Bot
Run with: uvicorn web.app:app --reload --port 8050
"""

import asyncio
import os
import threading
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager

from data.storage import Storage
from core.market_fetcher import MarketFetcher


storage = Storage()


def _start_bot_thread():
    """Start the bot scan loop in a background thread with auto-restart."""
    import time
    import traceback as tb
    from loguru import logger as bot_logger
    bot_logger.info("[BOT-THREAD] Thread function entered")
    while True:
        try:
            from core.engine import BotEngine
            bot_logger.info("[BOT-THREAD] Starting bot engine...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            engine = BotEngine(starting_capital=10_000.0)
            loop.run_until_complete(engine.run())
        except BaseException as e:
            bot_logger.error(f"[BOT-THREAD] ERROR — restarting in 60s: {type(e).__name__}: {e}")
            tb.print_exc()
            time.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.init()
    # Start bot thread when app starts
    bot_thread = threading.Thread(target=_start_bot_thread, daemon=True, name="BotEngine")
    bot_thread.start()
    print("[SERVER] Bot thread started", flush=True)
    yield


app = FastAPI(title="Phani Market Bot", lifespan=lifespan)


@app.get("/api/status")
async def api_status():
    """Health check — shows if bot has run and DB has data."""
    import os
    import threading
    from config.settings import settings
    db_exists = os.path.exists(settings.DB_PATH)
    perf = await storage.get_performance_summary() if db_exists else {}
    threads = [t.name for t in threading.enumerate()]
    return {
        "status": "ok",
        "db_exists": db_exists,
        "db_path": settings.DB_PATH,
        "total_trades": perf.get("total_trades", 0),
        "threads": threads,
        "thread_count": len(threads),
        "env_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "message": "Waiting for first scan..." if perf.get("total_trades", 0) == 0 else "Bot is running",
    }


@app.get("/api/portfolio")
async def api_portfolio():
    perf = await storage.get_performance_summary()
    return perf


@app.get("/api/trades")
async def api_trades():
    trades = await storage.get_open_trades()
    return trades


@app.get("/api/trades/closed")
async def api_closed_trades():
    import aiosqlite
    from config.settings import settings
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM paper_trades WHERE resolved = 1 ORDER BY exited_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


@app.get("/api/trades/all")
async def api_all_trades():
    import aiosqlite
    from config.settings import settings
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM paper_trades ORDER BY entered_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


@app.get("/api/reasoning")
async def api_reasoning():
    import aiosqlite
    from config.settings import settings
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reasoning_results ORDER BY reasoned_at DESC LIMIT 50"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Phani Market Bot - Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0e17; color: #e1e5ee; }

  .header {
    background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%);
    padding: 20px 30px;
    border-bottom: 1px solid #21262d;
    display: flex; justify-content: space-between; align-items: center;
  }
  .header h1 { font-size: 22px; color: #58a6ff; }
  .header .phase { background: #238636; color: #fff; padding: 4px 12px; border-radius: 12px; font-size: 12px; }
  .header .refresh { color: #8b949e; font-size: 13px; }

  .stats-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; padding: 20px 30px;
  }
  .stat-card {
    background: #161b22; border: 1px solid #21262d; border-radius: 10px;
    padding: 18px; text-align: center;
  }
  .stat-card .label { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .stat-card .value { font-size: 28px; font-weight: 700; margin-top: 6px; }
  .stat-card .value.green { color: #3fb950; }
  .stat-card .value.red { color: #f85149; }
  .stat-card .value.blue { color: #58a6ff; }
  .stat-card .value.yellow { color: #d29922; }

  .section { padding: 10px 30px 20px; }
  .section h2 { font-size: 16px; color: #c9d1d9; margin-bottom: 12px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { background: #161b22; color: #8b949e; text-align: left; padding: 10px 12px; font-weight: 600;
       text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; position: sticky; top: 0; }
  td { padding: 10px 12px; border-bottom: 1px solid #21262d; }
  tr:hover { background: #161b22; }

  .badge {
    padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;
    display: inline-block; min-width: 80px; text-align: center;
  }
  .badge.strong-buy { background: #238636; color: #fff; }
  .badge.buy { background: #1f6f2b; color: #aff5b4; }
  .badge.hold { background: #30363d; color: #8b949e; }
  .badge.sell { background: #8b3535; color: #ffc0c0; }
  .badge.strong-sell { background: #da3633; color: #fff; }

  .side-yes { color: #3fb950; font-weight: 600; }
  .side-no { color: #f85149; font-weight: 600; }
  .edge-pos { color: #3fb950; }
  .edge-neg { color: #f85149; }

  .table-wrap { overflow-x: auto; max-height: 500px; overflow-y: auto; border: 1px solid #21262d; border-radius: 8px; }

  .tabs { display: flex; gap: 4px; margin-bottom: 12px; }
  .tab {
    padding: 8px 16px; background: #21262d; border: none; color: #8b949e;
    cursor: pointer; border-radius: 6px; font-size: 13px;
  }
  .tab.active { background: #388bfd; color: #fff; }

  .footer { text-align: center; padding: 20px; color: #484f58; font-size: 12px; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Phani Market Bot</h1>
  </div>
  <div style="display:flex;align-items:center;gap:16px;">
    <span class="phase">PHASE 1 - PAPER</span>
    <span class="refresh" id="refreshTimer">Auto-refresh: 30s</span>
  </div>
</div>

<div class="stats-grid" id="statsGrid">
  <div class="stat-card"><div class="label">Total Trades</div><div class="value blue" id="totalTrades">-</div></div>
  <div class="stat-card"><div class="label">Open Positions</div><div class="value yellow" id="openTrades">-</div></div>
  <div class="stat-card"><div class="label">Closed Trades</div><div class="value" id="closedTrades">-</div></div>
  <div class="stat-card"><div class="label">Win Rate</div><div class="value" id="winRate">-</div></div>
  <div class="stat-card"><div class="label">Total P&L</div><div class="value" id="totalPnl">-</div></div>
  <div class="stat-card"><div class="label">Deployed Capital</div><div class="value blue" id="deployed">-</div></div>
</div>

<div class="section">
  <div class="tabs">
    <button class="tab active" onclick="showTab('open')">Open Positions</button>
    <button class="tab" onclick="showTab('closed')">Closed Trades</button>
    <button class="tab" onclick="showTab('reasoning')">Recent Reasoning</button>
  </div>

  <div id="tab-open" class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Side</th><th>Signal</th><th>Market</th>
        <th>Entry</th><th>Size</th><th>Our P</th><th>Market P</th><th>Edge</th><th>Conf</th><th>Opened</th>
      </tr></thead>
      <tbody id="openBody"></tbody>
    </table>
  </div>

  <div id="tab-closed" class="table-wrap" style="display:none">
    <table>
      <thead><tr>
        <th>#</th><th>Side</th><th>Signal</th><th>Market</th>
        <th>Entry</th><th>Exit</th><th>Size</th><th>P&L</th><th>Result</th><th>Closed</th>
      </tr></thead>
      <tbody id="closedBody"></tbody>
    </table>
  </div>

  <div id="tab-reasoning" class="table-wrap" style="display:none">
    <table>
      <thead><tr>
        <th>Market</th><th>Signal</th><th>Our P</th><th>Market P</th>
        <th>Edge</th><th>Conf</th><th>Raw LLM</th><th>Calibrated</th><th>Time</th>
      </tr></thead>
      <tbody id="reasoningBody"></tbody>
    </table>
  </div>
</div>

<div class="footer">Phani Market Bot v1 - Phase 1 Paper Trading - Auto-refreshes every 30 seconds</div>

<script>
function badgeClass(signal) {
  return signal.toLowerCase().replace('_', '-');
}

function fmtPct(v) { return (v * 100).toFixed(1) + '%'; }
function fmtUsd(v) { return '$' + Number(v).toFixed(2); }
function fmtDate(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}

async function loadPortfolio() {
  const res = await fetch('/api/portfolio');
  const d = await res.json();
  document.getElementById('totalTrades').textContent = d.total_trades;
  document.getElementById('openTrades').textContent = d.open_trades;
  document.getElementById('closedTrades').textContent = d.closed_trades;

  const wr = document.getElementById('winRate');
  wr.textContent = fmtPct(d.win_rate);
  wr.className = 'value ' + (d.win_rate >= 0.5 ? 'green' : d.closed_trades > 0 ? 'red' : '');

  const pnl = document.getElementById('totalPnl');
  pnl.textContent = (d.total_pnl_usd >= 0 ? '+' : '') + fmtUsd(d.total_pnl_usd);
  pnl.className = 'value ' + (d.total_pnl_usd >= 0 ? 'green' : 'red');

  document.getElementById('deployed').textContent = fmtUsd(d.deployed_capital);
}

async function loadOpenTrades() {
  const res = await fetch('/api/trades');
  const trades = await res.json();
  const tbody = document.getElementById('openBody');
  tbody.innerHTML = trades.map((t, i) => `<tr>
    <td>${i + 1}</td>
    <td class="${t.side === 'YES' ? 'side-yes' : 'side-no'}">${t.side}</td>
    <td><span class="badge ${badgeClass(t.signal)}">${t.signal}</span></td>
    <td title="${t.market_question}">${t.market_question.substring(0, 55)}</td>
    <td>${fmtPct(t.entry_price)}</td>
    <td>${fmtUsd(t.size_usd)}</td>
    <td>${fmtPct(t.our_probability)}</td>
    <td>${fmtPct(t.market_probability)}</td>
    <td class="${t.edge >= 0 ? 'edge-pos' : 'edge-neg'}">${(t.edge >= 0 ? '+' : '') + fmtPct(t.edge)}</td>
    <td>${fmtPct(t.confidence)}</td>
    <td>${fmtDate(t.entered_at)}</td>
  </tr>`).join('');
}

async function loadClosedTrades() {
  const res = await fetch('/api/trades/closed');
  const trades = await res.json();
  const tbody = document.getElementById('closedBody');
  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:#8b949e;padding:30px;">No closed trades yet - waiting for markets to resolve</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map((t, i) => `<tr>
    <td>${i + 1}</td>
    <td class="${t.side === 'YES' ? 'side-yes' : 'side-no'}">${t.side}</td>
    <td><span class="badge ${badgeClass(t.signal)}">${t.signal}</span></td>
    <td title="${t.market_question}">${t.market_question.substring(0, 55)}</td>
    <td>${fmtPct(t.entry_price)}</td>
    <td>${t.exit_price != null ? fmtPct(t.exit_price) : '-'}</td>
    <td>${fmtUsd(t.size_usd)}</td>
    <td class="${(t.pnl_usd || 0) >= 0 ? 'edge-pos' : 'edge-neg'}">${t.pnl_usd != null ? (t.pnl_usd >= 0 ? '+' : '') + fmtUsd(t.pnl_usd) : '-'}</td>
    <td>${t.pnl_usd != null ? (t.pnl_usd > 0 ? 'WIN' : 'LOSS') : '-'}</td>
    <td>${fmtDate(t.exited_at)}</td>
  </tr>`).join('');
}

async function loadReasoning() {
  const res = await fetch('/api/reasoning');
  const items = await res.json();
  const tbody = document.getElementById('reasoningBody');
  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#8b949e;padding:30px;">No reasoning results yet</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(r => `<tr>
    <td title="${r.market_question}">${r.market_question.substring(0, 50)}</td>
    <td><span class="badge ${badgeClass(r.signal)}">${r.signal}</span></td>
    <td>${fmtPct(r.our_probability)}</td>
    <td>${fmtPct(r.market_probability)}</td>
    <td class="${r.edge >= 0 ? 'edge-pos' : 'edge-neg'}">${(r.edge >= 0 ? '+' : '') + fmtPct(r.edge)}</td>
    <td>${fmtPct(r.confidence)}</td>
    <td>${fmtPct(r.raw_llm_probability)}</td>
    <td>${fmtPct(r.our_probability)}</td>
    <td>${fmtDate(r.reasoned_at)}</td>
  </tr>`).join('');
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('[id^="tab-"]').forEach(t => t.style.display = 'none');
  document.getElementById('tab-' + name).style.display = 'block';
  event.target.classList.add('active');
}

async function refresh() {
  await Promise.all([loadPortfolio(), loadOpenTrades(), loadClosedTrades(), loadReasoning()]);
}

refresh();
setInterval(refresh, 30000);

let countdown = 30;
setInterval(() => {
  countdown--;
  if (countdown <= 0) countdown = 30;
  document.getElementById('refreshTimer').textContent = 'Auto-refresh: ' + countdown + 's';
}, 1000);
</script>
</body>
</html>"""
