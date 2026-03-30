"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.MarketsProvider = exports.ReasoningProvider = exports.PortfolioProvider = void 0;
// ── Portfolio sidebar panel ───────────────────────────────────────────────────
class PortfolioProvider {
    constructor(_ctx, _bot) {
        this._ctx = _ctx;
        this._bot = _bot;
    }
    resolveWebviewView(view) {
        this._view = view;
        view.webview.options = { enableScripts: true };
        this._render();
    }
    refresh() { this._render(); }
    _render() {
        if (!this._view) {
            return;
        }
        const p = this._bot.portfolio;
        const pnlColor = (p?.totalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444';
        const pnlSign = (p?.totalPnl ?? 0) >= 0 ? '+' : '';
        this._view.webview.html = `<!DOCTYPE html><html><head><style>
        body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,sans-serif;margin:0;padding:8px;font-size:12px}
        .card{background:#1e293b;border:1px solid #334155;border-radius:7px;padding:10px;margin-bottom:8px}
        .label{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:3px}
        .value{font-size:18px;font-weight:700;color:#e2e8f0}
        .sub{font-size:10px;color:#475569;margin-top:2px}
        .phase{background:rgba(56,189,248,0.12);color:#38bdf8;padding:2px 8px;border-radius:10px;font-size:10px;display:inline-block;margin-bottom:8px}
        .paper{background:rgba(251,191,36,0.12);color:#fbbf24;padding:2px 8px;border-radius:10px;font-size:10px;display:inline-block;margin-bottom:8px;margin-left:4px}
        .grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
        </style></head><body>
        <div style="margin-bottom:6px"><span class="phase">Phase 1</span><span class="paper">Paper Only</span></div>
        <div class="grid">
          <div class="card"><div class="label">Capital</div><div class="value">$${(p?.currentCapital ?? 10000).toLocaleString()}</div><div class="sub">Started $${(p?.startingCapital ?? 10000).toLocaleString()}</div></div>
          <div class="card"><div class="label">P&L</div><div class="value" style="color:${pnlColor}">${pnlSign}$${Math.abs(p?.totalPnl ?? 0).toFixed(0)}</div><div class="sub">${pnlSign}${((p?.totalReturnPct ?? 0) * 100).toFixed(1)}% return</div></div>
          <div class="card"><div class="label">Win Rate</div><div class="value" style="color:${(p?.winRate ?? 0) >= 0.55 ? '#22c55e' : '#e2e8f0'}">${((p?.winRate ?? 0) * 100).toFixed(0)}%</div><div class="sub">${p?.closedPositions ?? 0} closed trades</div></div>
          <div class="card"><div class="label">Open Pos.</div><div class="value">${p?.openPositions ?? 0}</div><div class="sub">Avg edge ${((p?.avgEdge ?? 0) * 100).toFixed(1)}%</div></div>
        </div>
        </body></html>`;
    }
}
exports.PortfolioProvider = PortfolioProvider;
// ── Reasoning sidebar panel ───────────────────────────────────────────────────
class ReasoningProvider {
    constructor(_ctx, _bot) {
        this._ctx = _ctx;
        this._bot = _bot;
    }
    resolveWebviewView(view) {
        this._view = view;
        view.webview.options = { enableScripts: true };
        this._render();
    }
    refresh() { this._render(); }
    _render() {
        if (!this._view) {
            return;
        }
        const signal = this._bot.signals[0];
        const steps = signal?.steps ?? [];
        const stepNames = {
            reference_class: 'Reference class', base_rate: 'Base rate', inside_view: 'Inside view',
            outside_view: 'Outside view', news_adjustment: 'News adjustment', synthesis: 'Synthesis'
        };
        const stepHtml = steps.map((s, i) => `
            <div style="border-left:2px solid ${i === steps.length - 1 ? '#38bdf8' : '#334155'};padding-left:10px;margin-bottom:12px">
                <div style="font-size:10px;text-transform:uppercase;color:#38bdf8;letter-spacing:0.4px;margin-bottom:3px">${stepNames[s.stepName] || s.stepName}</div>
                <div style="font-size:11px;color:#475569;font-style:italic;margin-bottom:3px">${s.question}</div>
                <div style="font-size:11px;color:#94a3b8;line-height:1.5">${s.answer}</div>
                ${s.probabilityEstimate != null ? `<div style="font-size:11px;color:#22c55e;font-weight:600;margin-top:3px">→ ${(s.probabilityEstimate * 100).toFixed(0)}%</div>` : ''}
            </div>
        `).join('');
        this._view.webview.html = `<!DOCTYPE html><html><head><style>
        body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,sans-serif;margin:0;padding:8px;font-size:12px}
        .empty{color:#475569;text-align:center;padding:16px;font-size:11px}
        ::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#334155}
        </style></head><body>
        ${signal ? `
            <div style="font-size:11px;font-weight:600;color:#e2e8f0;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid #334155">${signal.market.substring(0, 70)}…</div>
            ${stepHtml || '<div class="empty">No reasoning steps yet</div>'}
        ` : `<div class="empty">Open the full dashboard,<br>click a signal to view reasoning.</div>`}
        </body></html>`;
    }
}
exports.ReasoningProvider = ReasoningProvider;
// ── Markets sidebar panel ─────────────────────────────────────────────────────
class MarketsProvider {
    constructor(_ctx, _bot) {
        this._ctx = _ctx;
        this._bot = _bot;
    }
    resolveWebviewView(view) {
        this._view = view;
        view.webview.options = { enableScripts: true };
        this._render();
    }
    refresh() { this._render(); }
    _render() {
        if (!this._view) {
            return;
        }
        const markets = this._bot.markets;
        const domainColors = { crypto: '#fbbf24', politics: '#a78bfa', economics: '#34d399' };
        const rows = markets.map(m => `
            <div style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:8px 9px;margin-bottom:6px">
                <div style="font-size:11px;color:#94a3b8;line-height:1.4;margin-bottom:4px">${m.question.substring(0, 65)}${m.question.length > 65 ? '…' : ''}</div>
                <div style="display:flex;gap:8px;font-size:10px;color:#475569">
                    <span style="color:${domainColors[m.domain] || '#94a3b8'}">${m.domain}</span>
                    <span>P: ${(m.yesPrice * 100).toFixed(0)}%</span>
                    <span>Vol: $${(m.volume24h / 1000).toFixed(0)}K</span>
                    <span>${m.daysToResolution}d left</span>
                </div>
            </div>
        `).join('');
        this._view.webview.html = `<!DOCTYPE html><html><head><style>
        body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,sans-serif;margin:0;padding:8px;font-size:12px}
        .empty{color:#475569;text-align:center;padding:16px;font-size:11px}
        ::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#334155}
        </style></head><body>
        ${rows || `<div class="empty">No qualified markets yet.<br>Run a scan first.</div>`}
        </body></html>`;
    }
}
exports.MarketsProvider = MarketsProvider;
//# sourceMappingURL=portfolioProvider.js.map