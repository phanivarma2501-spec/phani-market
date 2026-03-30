import * as vscode from 'vscode';
import { BotManager, Signal } from './botManager';

export class DashboardPanel {
    public static currentPanel: DashboardPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionUri: vscode.Uri, botManager: BotManager) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        if (DashboardPanel.currentPanel) {
            DashboardPanel.currentPanel._panel.reveal(column);
            DashboardPanel.currentPanel._update(botManager);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            'polymarketDashboard',
            'Polymarket Bot Dashboard',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
            }
        );
        DashboardPanel.currentPanel = new DashboardPanel(panel, extensionUri, botManager);
    }

    private constructor(
        panel: vscode.WebviewPanel,
        extensionUri: vscode.Uri,
        botManager: BotManager,
    ) {
        this._panel = panel;

        // Load demo data so the UI looks great immediately
        botManager.addDemoSignals();
        this._update(botManager);

        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        // Handle messages from webview
        this._panel.webview.onDidReceiveMessage(
            async (message) => {
                switch (message.command) {
                    case 'runScan':
                        await vscode.commands.executeCommand('polymarket.runScan');
                        this._update(botManager);
                        break;
                    case 'openSettings':
                        vscode.commands.executeCommand('polymarket.openSettings');
                        break;
                    case 'showReasoning':
                        this._panel.webview.postMessage({
                            command: 'showReasoning',
                            signal: botManager.signals.find(s => s.id === message.signalId),
                        });
                        break;
                    case 'refresh':
                        this._update(botManager);
                        break;
                }
            },
            null,
            this._disposables,
        );

        // Refresh every 30s if running
        botManager.onStateChange(() => this._update(botManager));
    }

    private _update(botManager: BotManager) {
        this._panel.webview.html = this._getHtml(botManager);
    }

    private _signalColor(signal: string): string {
        const colors: Record<string, string> = {
            'STRONG_BUY': '#22c55e',
            'BUY':        '#86efac',
            'HOLD':       '#94a3b8',
            'SELL':       '#f87171',
            'STRONG_SELL':'#ef4444',
        };
        return colors[signal] || '#94a3b8';
    }

    private _signalBg(signal: string): string {
        const colors: Record<string, string> = {
            'STRONG_BUY': 'rgba(34,197,94,0.12)',
            'BUY':        'rgba(134,239,172,0.10)',
            'HOLD':       'rgba(148,163,184,0.08)',
            'SELL':       'rgba(248,113,113,0.10)',
            'STRONG_SELL':'rgba(239,68,68,0.12)',
        };
        return colors[signal] || 'transparent';
    }

    private _domainTag(domain: string): string {
        const colors: Record<string, string> = {
            'crypto':    'rgba(251,191,36,0.15)',
            'politics':  'rgba(167,139,250,0.15)',
            'economics': 'rgba(52,211,153,0.15)',
        };
        const text: Record<string, string> = {
            'crypto':    '#fbbf24',
            'politics':  '#a78bfa',
            'economics': '#34d399',
        };
        const bg = colors[domain] || 'rgba(148,163,184,0.1)';
        const col = text[domain] || '#94a3b8';
        return `<span style="background:${bg};color:${col};padding:2px 7px;border-radius:4px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">${domain}</span>`;
    }

    private _formatTime(iso: string): string {
        try {
            const d = new Date(iso);
            return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
        } catch { return '—'; }
    }

    private _getHtml(botManager: BotManager): string {
        const signals = botManager.signals;
        const portfolio = botManager.portfolio;
        const markets = botManager.markets;
        const state = botManager.state;

        const pnlColor = (portfolio?.totalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444';
        const pnlSign  = (portfolio?.totalPnl ?? 0) >= 0 ? '+' : '';

        const signalRows = signals.map(s => `
            <tr class="signal-row" data-id="${s.id}" onclick="showReasoning('${s.id}')">
                <td>
                    <div style="font-size:13px;color:#e2e8f0;line-height:1.4;max-width:340px">${s.market.substring(0, 80)}${s.market.length > 80 ? '…' : ''}</div>
                    <div style="margin-top:4px">${this._domainTag(s.domain)}</div>
                </td>
                <td style="text-align:center">
                    <span style="background:${this._signalBg(s.signal)};color:${this._signalColor(s.signal)};padding:3px 10px;border-radius:5px;font-size:12px;font-weight:600;white-space:nowrap">${s.signal.replace('_', ' ')}</span>
                </td>
                <td style="text-align:center;color:#94a3b8;font-size:13px">${(s.ourProbability * 100).toFixed(0)}%</td>
                <td style="text-align:center;color:#94a3b8;font-size:13px">${(s.marketProbability * 100).toFixed(0)}%</td>
                <td style="text-align:center;font-size:13px;font-weight:600;color:${s.edge >= 0 ? '#22c55e' : '#ef4444'}">${s.edge >= 0 ? '+' : ''}${(s.edge * 100).toFixed(1)}%</td>
                <td style="text-align:center;color:#94a3b8;font-size:13px">${(s.confidence * 100).toFixed(0)}%</td>
                <td style="text-align:right;color:#94a3b8;font-size:13px">$${s.suggestedUsd.toFixed(0)}</td>
                <td style="text-align:right;color:#475569;font-size:11px">${this._formatTime(s.timestamp)}</td>
            </tr>
        `).join('');

        const marketRows = markets.map(m => `
            <tr>
                <td style="color:#e2e8f0;font-size:12px;max-width:280px">${m.question.substring(0, 70)}${m.question.length > 70 ? '…' : ''}</td>
                <td>${this._domainTag(m.domain)}</td>
                <td style="text-align:center;color:#94a3b8;font-size:12px">${(m.yesPrice * 100).toFixed(0)}%</td>
                <td style="text-align:right;color:#64748b;font-size:12px">$${(m.volume24h / 1000).toFixed(0)}K</td>
                <td style="text-align:right;color:#64748b;font-size:12px">${m.daysToResolution}d</td>
            </tr>
        `).join('');

        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polymarket Bot Dashboard</title>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:#0f172a; color:#e2e8f0; font-family: -apple-system, 'Segoe UI', sans-serif; height:100vh; overflow:hidden; display:flex; flex-direction:column; }
  .topbar { background:#1e293b; border-bottom:1px solid #334155; padding:10px 20px; display:flex; align-items:center; gap:16px; flex-shrink:0; }
  .logo { font-size:15px; font-weight:700; color:#38bdf8; letter-spacing:-0.3px; }
  .phase-badge { background:rgba(56,189,248,0.12); color:#38bdf8; padding:2px 10px; border-radius:12px; font-size:11px; font-weight:600; }
  .paper-badge { background:rgba(251,191,36,0.12); color:#fbbf24; padding:2px 10px; border-radius:12px; font-size:11px; font-weight:600; }
  .status-dot { width:8px; height:8px; border-radius:50%; background:${state === 'running' ? '#22c55e' : state === 'signal' ? '#f59e0b' : '#475569'}; ${state === 'running' ? 'animation: pulse 1s infinite;' : ''} }
  .status-text { font-size:12px; color:#94a3b8; }
  .spacer { flex:1; }
  .btn { background:#1e293b; border:1px solid #334155; color:#e2e8f0; padding:6px 14px; border-radius:6px; font-size:12px; cursor:pointer; transition:all 0.15s; }
  .btn:hover { background:#334155; }
  .btn-primary { background:#38bdf8; border-color:#38bdf8; color:#0f172a; font-weight:600; }
  .btn-primary:hover { background:#7dd3fc; }
  .main { display:grid; grid-template-columns:1fr 1fr 1fr; grid-template-rows:auto 1fr 1fr; gap:12px; padding:12px; flex:1; overflow:hidden; }
  .card { background:#1e293b; border:1px solid #334155; border-radius:10px; padding:14px; overflow:hidden; display:flex; flex-direction:column; }
  .card-title { font-size:11px; text-transform:uppercase; letter-spacing:0.6px; color:#64748b; font-weight:600; margin-bottom:10px; flex-shrink:0; }
  .metric-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .metric { background:#0f172a; border-radius:7px; padding:10px 12px; }
  .metric-label { font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.4px; margin-bottom:3px; }
  .metric-value { font-size:20px; font-weight:700; color:#e2e8f0; }
  .metric-value.pos { color:#22c55e; }
  .metric-value.neg { color:#ef4444; }
  .metric-sub { font-size:10px; color:#475569; margin-top:2px; }
  .signals-card { grid-column:1/-1; }
  .table-wrap { overflow-y:auto; flex:1; }
  table { width:100%; border-collapse:collapse; }
  th { font-size:10px; text-transform:uppercase; letter-spacing:0.4px; color:#475569; padding:6px 8px; text-align:left; border-bottom:1px solid #1e293b; position:sticky; top:0; background:#1e293b; z-index:1; }
  td { padding:8px 8px; border-bottom:1px solid rgba(51,65,85,0.4); vertical-align:middle; }
  .signal-row { cursor:pointer; transition:background 0.1s; }
  .signal-row:hover { background:rgba(56,189,248,0.05); }
  .reasoning-panel { background:#0f172a; border-radius:8px; padding:14px; overflow-y:auto; flex:1; }
  .step { margin-bottom:14px; border-left:2px solid #334155; padding-left:12px; }
  .step.active { border-left-color:#38bdf8; }
  .step-name { font-size:10px; text-transform:uppercase; letter-spacing:0.4px; color:#38bdf8; margin-bottom:4px; }
  .step-q { font-size:11px; color:#64748b; font-style:italic; margin-bottom:4px; }
  .step-a { font-size:12px; color:#94a3b8; line-height:1.5; }
  .step-p { font-size:12px; color:#22c55e; font-weight:600; margin-top:4px; }
  .no-signal { color:#475569; font-size:13px; text-align:center; padding:30px; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  ::-webkit-scrollbar { width:4px; } ::-webkit-scrollbar-track { background:transparent; } ::-webkit-scrollbar-thumb { background:#334155; border-radius:2px; }
</style>
</head>
<body>

<div class="topbar">
  <span class="logo">⬡ Polymarket Bot</span>
  <span class="phase-badge">Phase 1</span>
  <span class="paper-badge">Paper Only</span>
  <div class="status-dot"></div>
  <span class="status-text">${state === 'running' ? 'Scanning...' : state === 'signal' ? `${signals.length} signal(s)` : 'Idle'}</span>
  <div class="spacer"></div>
  <button class="btn btn-primary" onclick="runScan()">▶ Run Scan</button>
  <button class="btn" onclick="openSettings()">⚙ Settings</button>
</div>

<div class="main">

  <!-- Portfolio stats -->
  <div class="card">
    <div class="card-title">Paper Portfolio</div>
    <div class="metric-grid">
      <div class="metric">
        <div class="metric-label">Capital</div>
        <div class="metric-value">$${(portfolio?.currentCapital ?? 10000).toLocaleString()}</div>
        <div class="metric-sub">Started $${(portfolio?.startingCapital ?? 10000).toLocaleString()}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Total P&L</div>
        <div class="metric-value ${(portfolio?.totalPnl ?? 0) >= 0 ? 'pos' : 'neg'}">${pnlSign}$${Math.abs(portfolio?.totalPnl ?? 0).toFixed(0)}</div>
        <div class="metric-sub">${pnlSign}${((portfolio?.totalReturnPct ?? 0) * 100).toFixed(1)}% return</div>
      </div>
      <div class="metric">
        <div class="metric-label">Win Rate</div>
        <div class="metric-value ${(portfolio?.winRate ?? 0) >= 0.55 ? 'pos' : ''}">${((portfolio?.winRate ?? 0) * 100).toFixed(0)}%</div>
        <div class="metric-sub">${portfolio?.closedPositions ?? 0} closed</div>
      </div>
      <div class="metric">
        <div class="metric-label">Open Positions</div>
        <div class="metric-value">${portfolio?.openPositions ?? 0}</div>
        <div class="metric-sub">Avg edge ${((portfolio?.avgEdge ?? 0) * 100).toFixed(1)}%</div>
      </div>
    </div>
  </div>

  <!-- Qualified markets -->
  <div class="card" style="grid-column:2/4">
    <div class="card-title">Qualified Markets (${markets.length})</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Question</th><th>Domain</th><th style="text-align:center">Market P</th>
          <th style="text-align:right">Vol 24h</th><th style="text-align:right">Days</th>
        </tr></thead>
        <tbody>${marketRows || '<tr><td colspan="5" class="no-signal">No markets yet — run a scan</td></tr>'}</tbody>
      </table>
    </div>
  </div>

  <!-- Signals table -->
  <div class="card signals-card" style="grid-row:2">
    <div class="card-title">Live Signals (${signals.length}) — click a row to see reasoning</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Market</th><th style="text-align:center">Signal</th>
          <th style="text-align:center">Our P</th><th style="text-align:center">Market P</th>
          <th style="text-align:center">Edge</th><th style="text-align:center">Conf</th>
          <th style="text-align:right">Size</th><th style="text-align:right">Time</th>
        </tr></thead>
        <tbody id="signalBody">
          ${signalRows || '<tr><td colspan="8" class="no-signal">No signals yet — run a scan to start</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Reasoning chain -->
  <div class="card" style="grid-column:2/-1;grid-row:2">
    <div class="card-title">Reasoning Chain</div>
    <div class="reasoning-panel" id="reasoningPanel">
      <div class="no-signal">Click a signal row to see the 6-step superforecasting reasoning</div>
    </div>
  </div>

</div>

<script>
const vscode = acquireVsCodeApi();

function runScan() { vscode.postMessage({ command: 'runScan' }); }
function openSettings() { vscode.postMessage({ command: 'openSettings' }); }

function showReasoning(signalId) {
    vscode.postMessage({ command: 'showReasoning', signalId });
}

window.addEventListener('message', event => {
    const msg = event.data;
    if (msg.command === 'showReasoning' && msg.signal) {
        const s = msg.signal;
        const steps = s.steps || [];
        const panel = document.getElementById('reasoningPanel');
        if (!panel) return;

        const stepNames = { reference_class:'Reference class', base_rate:'Base rate', inside_view:'Inside view', outside_view:'Outside view', news_adjustment:'News adjustment', synthesis:'Synthesis' };

        panel.innerHTML = \`
            <div style="margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #334155">
                <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:4px">\${s.market}</div>
                <div style="display:flex;gap:10px;flex-wrap:wrap">
                    <span style="color:#22c55e;font-size:12px">Our P: \${(s.ourProbability*100).toFixed(0)}%</span>
                    <span style="color:#94a3b8;font-size:12px">Market P: \${(s.marketProbability*100).toFixed(0)}%</span>
                    <span style="color:\${s.edge>=0?'#22c55e':'#ef4444'};font-size:12px;font-weight:600">Edge: \${s.edge>=0?'+':''}\${(s.edge*100).toFixed(1)}%</span>
                    <span style="color:#94a3b8;font-size:12px">Confidence: \${(s.confidence*100).toFixed(0)}%</span>
                </div>
            </div>
            \${steps.map((step, i) => \`
                <div class="step \${i===steps.length-1?'active':''}">
                    <div class="step-name">\${stepNames[step.stepName] || step.stepName}</div>
                    <div class="step-q">\${step.question}</div>
                    <div class="step-a">\${step.answer}</div>
                    \${step.probabilityEstimate != null ? \`<div class="step-p">→ \${(step.probabilityEstimate*100).toFixed(0)}% probability</div>\` : ''}
                </div>
            \`).join('')}
            \${steps.length === 0 ? '<div class="no-signal">No reasoning steps available — run a new scan to generate detailed reasoning</div>' : ''}
        \`;
    }
});
</script>
</body>
</html>`;
    }

    public dispose() {
        DashboardPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            this._disposables.pop()?.dispose();
        }
    }
}
