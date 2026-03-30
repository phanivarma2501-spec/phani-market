import * as vscode from 'vscode';
import { BotManager } from './botManager';
import { DashboardPanel } from './dashboardPanel';
import { SignalsProvider } from './providers/signalsProvider';
import { PortfolioProvider } from './providers/portfolioProvider';
import { ReasoningProvider } from './providers/reasoningProvider';
import { MarketsProvider } from './providers/marketsProvider';

let botManager: BotManager;

export function activate(context: vscode.ExtensionContext) {
    console.log('Polymarket Bot extension activating...');

    // Core bot manager — controls the Python process
    botManager = new BotManager(context);

    // Webview providers for sidebar panels
    const signalsProvider   = new SignalsProvider(context, botManager);
    const portfolioProvider = new PortfolioProvider(context, botManager);
    const reasoningProvider = new ReasoningProvider(context, botManager);
    const marketsProvider   = new MarketsProvider(context, botManager);

    // Register sidebar webview providers
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('polymarket.signals',   signalsProvider),
        vscode.window.registerWebviewViewProvider('polymarket.portfolio', portfolioProvider),
        vscode.window.registerWebviewViewProvider('polymarket.reasoning', reasoningProvider),
        vscode.window.registerWebviewViewProvider('polymarket.markets',   marketsProvider),
    );

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('polymarket.runScan', async () => {
            const apiKey = vscode.workspace.getConfiguration('polymarket').get<string>('anthropicApiKey');
            if (!apiKey) {
                const go = await vscode.window.showErrorMessage(
                    'Polymarket Bot: Anthropic API key not configured.',
                    'Open Settings'
                );
                if (go) { vscode.commands.executeCommand('polymarket.openSettings'); }
                return;
            }
            await botManager.runScan();
            signalsProvider.refresh();
            portfolioProvider.refresh();
        }),

        vscode.commands.registerCommand('polymarket.runOnce', async () => {
            await botManager.runOnce();
            signalsProvider.refresh();
            portfolioProvider.refresh();
            reasoningProvider.refresh();
        }),

        vscode.commands.registerCommand('polymarket.showStatus', async () => {
            await botManager.showStatus();
            portfolioProvider.refresh();
        }),

        vscode.commands.registerCommand('polymarket.openSettings', () => {
            vscode.commands.executeCommand(
                'workbench.action.openSettings',
                '@ext:kauma-phani.polymarket-bot'
            );
        }),

        vscode.commands.registerCommand('polymarket.openDashboard', () => {
            DashboardPanel.createOrShow(context.extensionUri, botManager);
        }),

        vscode.commands.registerCommand('polymarket.stopBot', async () => {
            await botManager.stop();
            vscode.window.showInformationMessage('Polymarket Bot stopped.');
        }),
    );

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
    const autoStart = vscode.workspace.getConfiguration('polymarket').get<boolean>('autoStartOnOpen');
    if (autoStart) {
        vscode.commands.executeCommand('polymarket.runScan');
    }

    vscode.window.showInformationMessage(
        '🤖 Polymarket Bot ready. Open the sidebar (activity bar) to start.',
        'Open Dashboard'
    ).then(action => {
        if (action === 'Open Dashboard') {
            vscode.commands.executeCommand('polymarket.openDashboard');
        }
    });
}

export function deactivate() {
    botManager?.stop();
}
