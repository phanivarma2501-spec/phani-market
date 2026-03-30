"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.SignalsProvider = void 0;
const vscode = __importStar(require("vscode"));
class SignalsProvider {
    constructor(_context, _botManager) {
        this._context = _context;
        this._botManager = _botManager;
    }
    resolveWebviewView(view) {
        this._view = view;
        view.webview.options = { enableScripts: true };
        this._render();
        view.webview.onDidReceiveMessage(msg => {
            if (msg.command === 'openDashboard') {
                vscode.commands.executeCommand('polymarket.openDashboard');
            }
        });
    }
    refresh() { this._render(); }
    _render() {
        if (!this._view) {
            return;
        }
        const signals = this._botManager.signals.slice(0, 8);
        const sigColors = {
            'STRONG_BUY': '#22c55e', 'BUY': '#86efac', 'HOLD': '#94a3b8', 'SELL': '#f87171', 'STRONG_SELL': '#ef4444'
        };
        const rows = signals.map(s => `
            <div class="sig" onclick="openDash()">
                <div class="sig-signal" style="color:${sigColors[s.signal] || '#94a3b8'}">${s.signal.replace('_', ' ')}</div>
                <div class="sig-market">${s.market.substring(0, 55)}${s.market.length > 55 ? '…' : ''}</div>
                <div class="sig-meta">Edge: <b style="color:${s.edge >= 0 ? '#22c55e' : '#ef4444'}">${s.edge >= 0 ? '+' : ''}${(s.edge * 100).toFixed(1)}%</b> · Conf: ${(s.confidence * 100).toFixed(0)}% · $${s.suggestedUsd.toFixed(0)}</div>
            </div>
        `).join('');
        this._view.webview.html = `<!DOCTYPE html><html><head><style>
        body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,sans-serif;font-size:12px;margin:0;padding:8px}
        .empty{color:#475569;text-align:center;padding:20px 8px;font-size:11px}
        .sig{background:#1e293b;border:1px solid #334155;border-radius:7px;padding:9px 10px;margin-bottom:7px;cursor:pointer;transition:border-color 0.15s}
        .sig:hover{border-color:#38bdf8}
        .sig-signal{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:3px}
        .sig-market{color:#94a3b8;font-size:11px;line-height:1.4;margin-bottom:4px}
        .sig-meta{color:#475569;font-size:10px}
        .open-btn{width:100%;background:#1e293b;border:1px solid #334155;color:#38bdf8;padding:7px;border-radius:6px;font-size:11px;cursor:pointer;margin-top:4px}
        .open-btn:hover{background:#334155}
        </style></head><body>
        ${rows || `<div class="empty">No signals yet.<br>Run a scan to start.</div>`}
        <button class="open-btn" onclick="openDash()">Open Full Dashboard →</button>
        <script>
        const vscode=acquireVsCodeApi();
        function openDash(){vscode.postMessage({command:'openDashboard'});}
        </script></body></html>`;
    }
}
exports.SignalsProvider = SignalsProvider;
//# sourceMappingURL=signalsProvider.js.map