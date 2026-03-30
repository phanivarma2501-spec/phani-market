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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const botManager_1 = require("./botManager");
const dashboardPanel_1 = require("./dashboardPanel");
const signalsProvider_1 = require("./providers/signalsProvider");
const portfolioProvider_1 = require("./providers/portfolioProvider");
const reasoningProvider_1 = require("./providers/reasoningProvider");
const marketsProvider_1 = require("./providers/marketsProvider");
let botManager;
function activate(context) {
    console.log('Polymarket Bot extension activating...');
    // Core bot manager — controls the Python process
    botManager = new botManager_1.BotManager(context);
    // Webview providers for sidebar panels
    const signalsProvider = new signalsProvider_1.SignalsProvider(context, botManager);
    const portfolioProvider = new portfolioProvider_1.PortfolioProvider(context, botManager);
    const reasoningProvider = new reasoningProvider_1.ReasoningProvider(context, botManager);
    const marketsProvider = new marketsProvider_1.MarketsProvider(context, botManager);
    // Register sidebar webview providers
    context.subscriptions.push(vscode.window.registerWebviewViewProvider('polymarket.signals', signalsProvider), vscode.window.registerWebviewViewProvider('polymarket.portfolio', portfolioProvider), vscode.window.registerWebviewViewProvider('polymarket.reasoning', reasoningProvider), vscode.window.registerWebviewViewProvider('polymarket.markets', marketsProvider));
    // Register commands
    context.subscriptions.push(vscode.commands.registerCommand('polymarket.runScan', async () => {
        const apiKey = vscode.workspace.getConfiguration('polymarket').get('anthropicApiKey');
        if (!apiKey) {
            const go = await vscode.window.showErrorMessage('Polymarket Bot: Anthropic API key not configured.', 'Open Settings');
            if (go) {
                vscode.commands.executeCommand('polymarket.openSettings');
            }
            return;
        }
        await botManager.runScan();
        signalsProvider.refresh();
        portfolioProvider.refresh();
    }), vscode.commands.registerCommand('polymarket.runOnce', async () => {
        await botManager.runOnce();
        signalsProvider.refresh();
        portfolioProvider.refresh();
        reasoningProvider.refresh();
    }), vscode.commands.registerCommand('polymarket.showStatus', async () => {
        await botManager.showStatus();
        portfolioProvider.refresh();
    }), vscode.commands.registerCommand('polymarket.openSettings', () => {
        vscode.commands.executeCommand('workbench.action.openSettings', '@ext:kauma-phani.polymarket-bot');
    }), vscode.commands.registerCommand('polymarket.openDashboard', () => {
        dashboardPanel_1.DashboardPanel.createOrShow(context.extensionUri, botManager);
    }), vscode.commands.registerCommand('polymarket.stopBot', async () => {
        await botManager.stop();
        vscode.window.showInformationMessage('Polymarket Bot stopped.');
    }));
    // Status bar item
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.command = 'polymarket.openDashboard';
    statusBar.text = '$(graph) Poly: Idle';
    statusBar.tooltip = 'Polymarket Bot — click to open dashboard';
    statusBar.show();
    context.subscriptions.push(statusBar);
    // Update status bar when bot state changes
    botManager.onStateChange((state) => {
        statusBar.text = state === 'running'
            ? '$(sync~spin) Poly: Scanning'
            : state === 'signal'
                ? '$(bell) Poly: Signal!'
                : '$(graph) Poly: Idle';
    });
    // Auto-start if configured
    const autoStart = vscode.workspace.getConfiguration('polymarket').get('autoStartOnOpen');
    if (autoStart) {
        vscode.commands.executeCommand('polymarket.runScan');
    }
    vscode.window.showInformationMessage('🤖 Polymarket Bot ready. Open the sidebar (activity bar) to start.', 'Open Dashboard').then(action => {
        if (action === 'Open Dashboard') {
            vscode.commands.executeCommand('polymarket.openDashboard');
        }
    });
}
function deactivate() {
    botManager?.stop();
}
//# sourceMappingURL=extension.js.map