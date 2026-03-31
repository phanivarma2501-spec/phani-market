"""
server.py - Combined bot + web dashboard for Railway deployment
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import threading
import traceback
import uvicorn
from web.app import app
from core.engine import BotEngine


def run_bot():
    """Run the bot scan loop in a separate thread."""
    try:
        print("[BOT] Starting bot engine...", flush=True)
        engine = BotEngine(starting_capital=10_000.0)
        asyncio.run(engine.run())
    except Exception as e:
        print(f"[BOT] FATAL ERROR: {e}", flush=True)
        traceback.print_exc()


print("[SERVER] Starting phani-market server...", flush=True)

# Start bot in background thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
print("[SERVER] Bot thread started", flush=True)

# Start web dashboard
port = int(os.environ.get("PORT", 8050))
print(f"[SERVER] Starting dashboard on port {port}", flush=True)
uvicorn.run(app, host="0.0.0.0", port=port)
