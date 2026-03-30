import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export type BotState = 'idle' | 'running' | 'signal' | 'error';

export interface Signal {
    id: string;
    market: string;
    signal: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL';
    ourProbability: number;
    marketProbability: number;
    edge: number;
    confidence: number;
    suggestedUsd: number;
    timestamp: string;
    domain: string;
    steps?: ReasoningStep[];
}

export interface ReasoningStep {
    stepName: string;
    question: string;
    answer: string;
    probabilityEstimate?: number;
    confidence?: number;
}

export interface PortfolioStats {
    currentCapital: number;
    startingCapital: number;
    totalPnl: number;
    totalReturnPct: number;
    openPositions: number;
    closedPositions: number;
    winRate: number;
    avgEdge: number;
    phase: number;
}

export interface MarketInfo {
    conditionId: string;
    question: string;
    domain: string;
    yesPrice: number;
    volume24h: number;
    liquidity: number;
    daysToResolution: number;
}

export class BotManager {
    private _state: BotState = 'idle';
    private _signals: Signal[] = [];
    private _portfolio: PortfolioStats | null = null;
    private _markets: MarketInfo[] = [];
    private _latestReasoning: ReasoningStep[] = [];
    private _output: vscode.OutputChannel;
    private _process: cp.ChildProcess | null = null;
    private _stateChangeEmitter = new vscode.EventEmitter<BotState>();
    private _context: vscode.ExtensionContext;
    private _botPath: string = '';

    constructor(context: vscode.ExtensionContext) {
        this._context = context;
        this._output = vscode.window.createOutputChannel('Polymarket Bot');
        this._botPath = this._findBotPath();
        this._loadPersistedState();
    }

    get state(): BotState { return this._state; }
    get signals(): Signal[] { return this._signals; }
    get portfolio(): PortfolioStats | null { return this._portfolio; }
    get markets(): MarketInfo[] { return this._markets; }
    get latestReasoning(): ReasoningStep[] { return this._latestReasoning; }
    get outputChannel(): vscode.OutputChannel { return this._output; }

    onStateChange(listener: (state: BotState) => void): vscode.Disposable {
        return this._stateChangeEmitter.event(listener);
    }

    private _setState(state: BotState) {
        this._state = state;
        this._stateChangeEmitter.fire(state);
    }

    private _findBotPath(): string {
        // 1. Check VS Code setting
        const configured = vscode.workspace.getConfiguration('polymarket').get<string>('botPath');
        if (configured && fs.existsSync(path.join(configured, 'main.py'))) {
            return configured;
        }
        // 2. Check workspace root
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (workspaceFolders) {
            for (const folder of workspaceFolders) {
                const candidate = path.join(folder.uri.fsPath, 'polymarket_bot');
                if (fs.existsSync(path.join(candidate, 'main.py'))) {
                    return candidate;
                }
                // Also try root
                if (fs.existsSync(path.join(folder.uri.fsPath, 'main.py'))) {
                    return folder.uri.fsPath;
                }
            }
        }
        // 3. Home directory default
        const homeBot = path.join(process.env.HOME || '~', 'polymarket_bot');
        if (fs.existsSync(path.join(homeBot, 'main.py'))) {
            return homeBot;
        }
        return '';
    }

    private _getConfig() {
        const cfg = vscode.workspace.getConfiguration('polymarket');
        return {
            apiKey:         cfg.get<string>('anthropicApiKey', ''),
            telegramToken:  cfg.get<string>('telegramBotToken', ''),
            telegramChatId: cfg.get<string>('telegramChatId', ''),
            domains:        cfg.get<string[]>('focusDomains', ['crypto', 'politics', 'economics']),
            minEdge:        cfg.get<number>('minEdge', 0.06),
            minConfidence:  cfg.get<number>('minConfidence', 0.65),
            startingCapital:cfg.get<number>('startingCapital', 10000),
            scanInterval:   cfg.get<number>('scanIntervalMinutes', 15),
        };
    }

    private _buildEnv(): NodeJS.ProcessEnv {
        const cfg = this._getConfig();
        return {
            ...process.env,
            ANTHROPIC_API_KEY:      cfg.apiKey,
            TELEGRAM_BOT_TOKEN:     cfg.telegramToken,
            TELEGRAM_CHAT_ID:       cfg.telegramChatId,
            FOCUS_DOMAINS:          JSON.stringify(cfg.domains),
            MIN_EDGE_TO_FLAG:       String(cfg.minEdge),
            REASONING_CONFIDENCE_MIN: String(cfg.minConfidence),
            LIVE_TRADING_ENABLED:   'False',
            PAPER_TRADING:          'True',
            PHASE:                  '1',
            PYTHONPATH:             this._botPath,
        };
    }

    private _runPython(args: string[]): Promise<string> {
        return new Promise((resolve, reject) => {
            if (!this._botPath) {
                reject(new Error('Bot path not configured. Set polymarket.botPath in settings.'));
                return;
            }
            const env = this._buildEnv();
            const proc = cp.spawn('python3', [path.join(this._botPath, 'main.py'), ...args], {
                env,
                cwd: this._botPath,
            });
            let stdout = '';
            let stderr = '';
            proc.stdout.on('data', (d: Buffer) => {
                stdout += d.toString();
                this._output.append(d.toString());
            });
            proc.stderr.on('data', (d: Buffer) => {
                stderr += d.toString();
                this._output.append(d.toString());
            });
            proc.on('close', (code) => {
                if (code === 0) { resolve(stdout); }
                else { reject(new Error(stderr || `Process exited with code ${code}`)); }
            });
            this._process = proc;
        });
    }

    async runScan(): Promise<void> {
        if (this._state === 'running') {
            vscode.window.showWarningMessage('Bot is already running a scan.');
            return;
        }
        this._setState('running');
        this._output.show(true);
        this._output.appendLine('\n=== Starting market scan ===');

        try {
            const output = await this._runPython(['once']);
            this._parseOutput(output);
            this._setState(this._signals.length > 0 ? 'signal' : 'idle');
            this._persistState();
            vscode.window.showInformationMessage(
                `Scan complete. ${this._signals.length} signal(s) found.`,
                'View Signals'
            ).then(a => {
                if (a === 'View Signals') {
                    vscode.commands.executeCommand('polymarket.openDashboard');
                }
            });
        } catch (e: any) {
            this._setState('error');
            vscode.window.showErrorMessage(`Bot error: ${e.message}`);
        }
    }

    async runOnce(): Promise<void> {
        return this.runScan();
    }

    async showStatus(): Promise<void> {
        this._output.show();
        this._output.appendLine('\n=== Portfolio Status ===');
        try {
            await this._runPython(['status']);
            await this._refreshPortfolio();
        } catch (e: any) {
            this._output.appendLine(`Error: ${e.message}`);
        }
    }

    async stop(): Promise<void> {
        if (this._process) {
            this._process.kill();
            this._process = null;
        }
        this._setState('idle');
    }

    private async _refreshPortfolio(): Promise<void> {
        // In production: read from SQLite DB directly via Python
        // For now parse from status output
        this._portfolio = {
            currentCapital:  this._context.globalState.get('currentCapital', 10000),
            startingCapital: this._getConfig().startingCapital,
            totalPnl:        this._context.globalState.get('totalPnl', 0),
            totalReturnPct:  this._context.globalState.get('totalReturnPct', 0),
            openPositions:   this._context.globalState.get('openPositions', 0),
            closedPositions: this._context.globalState.get('closedPositions', 0),
            winRate:         this._context.globalState.get('winRate', 0),
            avgEdge:         this._context.globalState.get('avgEdge', 0),
            phase:           1,
        };
    }

    private _parseOutput(output: string): void {
        // Parse signals from log output
        const signalRegex = /PAPER TRADE OPENED: (YES|NO) '(.+?)' \| \$([0-9.]+) @ ([0-9.]+) \| Edge: ([+-][0-9.]+)% \| Conf: ([0-9]+)% \| Signal: (\w+)/g;
        let match;
        while ((match = signalRegex.exec(output)) !== null) {
            const [, side, market, sizeUsd, entryPrice, edge, conf, signal] = match;
            const existing = this._signals.find(s => s.market === market);
            if (!existing) {
                this._signals.unshift({
                    id:               `${Date.now()}-${Math.random()}`,
                    market,
                    signal:           signal as Signal['signal'],
                    ourProbability:   parseFloat(entryPrice),
                    marketProbability: parseFloat(entryPrice),
                    edge:             parseFloat(edge) / 100,
                    confidence:       parseFloat(conf) / 100,
                    suggestedUsd:     parseFloat(sizeUsd),
                    timestamp:        new Date().toISOString(),
                    domain:           'unknown',
                });
            }
        }
        // Keep only last 50 signals
        this._signals = this._signals.slice(0, 50);
    }

    addDemoSignals(): void {
        // Demo data for testing UI without running Python
        this._signals = [
            {
                id: '1',
                market: 'Will the Fed cut rates at the May 2026 FOMC meeting?',
                signal: 'STRONG_BUY',
                ourProbability: 0.68,
                marketProbability: 0.51,
                edge: 0.17,
                confidence: 0.78,
                suggestedUsd: 340,
                timestamp: new Date().toISOString(),
                domain: 'economics',
                steps: [
                    { stepName: 'reference_class', question: 'What reference class?', answer: 'Fed rate decisions following cooling inflation — historically 65% cut probability when CPI drops below 3%.' },
                    { stepName: 'base_rate', question: 'Base rate?', answer: 'Historical Fed cut at next meeting when inflation trending down: ~45%. Current conditions push above base.', probabilityEstimate: 0.58 },
                    { stepName: 'inside_view', question: 'Case-specific factors?', answer: 'March CPI printed 2.9%, below expectations. Fed dot plot signalled 2 cuts in 2026. Job market softening slightly.', probabilityEstimate: 0.65 },
                    { stepName: 'outside_view', question: 'Systemic adjustments?', answer: 'Markets tend to over-price rate cuts. Resolution source is clear (FOMC statement). No ambiguity risk.', probabilityEstimate: 0.64 },
                    { stepName: 'news_adjustment', question: 'Recent news impact?', answer: 'Bloomberg (2h ago): Fed governor hinted at May cut. Reuters: CPI miss solidifies expectations. Both push probability up.', probabilityEstimate: 0.70 },
                    { stepName: 'synthesis', question: 'Final synthesis?', answer: 'Strong confluence: cooling inflation, Fed communication, market pricing all align. Calibrated to 68% (from raw 72% after Platt scaling).', probabilityEstimate: 0.68, confidence: 0.78 },
                ],
            },
            {
                id: '2',
                market: 'Will Bitcoin close above $95,000 on April 30, 2026?',
                signal: 'BUY',
                ourProbability: 0.61,
                marketProbability: 0.50,
                edge: 0.11,
                confidence: 0.69,
                suggestedUsd: 180,
                timestamp: new Date(Date.now() - 3600000).toISOString(),
                domain: 'crypto',
            },
            {
                id: '3',
                market: 'Will Narendra Modi remain PM of India through 2026?',
                signal: 'HOLD',
                ourProbability: 0.82,
                marketProbability: 0.80,
                edge: 0.02,
                confidence: 0.71,
                suggestedUsd: 0,
                timestamp: new Date(Date.now() - 7200000).toISOString(),
                domain: 'politics',
            },
        ];
        this._markets = [
            { conditionId: 'a1', question: 'Will the Fed cut rates at May 2026 FOMC?', domain: 'economics', yesPrice: 0.51, volume24h: 125000, liquidity: 380000, daysToResolution: 28 },
            { conditionId: 'a2', question: 'Will Bitcoin close above $95,000 on April 30?', domain: 'crypto', yesPrice: 0.50, volume24h: 89000, liquidity: 210000, daysToResolution: 30 },
            { conditionId: 'a3', question: 'Will the US CPI print above 3% in March 2026?', domain: 'economics', yesPrice: 0.38, volume24h: 45000, liquidity: 95000, daysToResolution: 12 },
            { conditionId: 'a4', question: 'Will Narendra Modi remain PM of India through 2026?', domain: 'politics', yesPrice: 0.80, volume24h: 22000, liquidity: 65000, daysToResolution: 275 },
            { conditionId: 'a5', question: 'Will ETH price exceed $4,000 by May 2026?', domain: 'crypto', yesPrice: 0.42, volume24h: 67000, liquidity: 155000, daysToResolution: 31 },
        ];
        this._portfolio = {
            currentCapital: 10843,
            startingCapital: 10000,
            totalPnl: 843,
            totalReturnPct: 0.0843,
            openPositions: 2,
            closedPositions: 7,
            winRate: 0.714,
            avgEdge: 0.092,
            phase: 1,
        };
        this._setState('signal');
    }

    private _persistState(): void {
        this._context.globalState.update('signals', this._signals);
        if (this._portfolio) {
            this._context.globalState.update('currentCapital', this._portfolio.currentCapital);
            this._context.globalState.update('totalPnl', this._portfolio.totalPnl);
        }
    }

    private _loadPersistedState(): void {
        this._signals = this._context.globalState.get<Signal[]>('signals', []);
        this._refreshPortfolio();
    }
}
