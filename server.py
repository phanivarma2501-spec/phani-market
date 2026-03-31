"""
server.py - Combined bot + web dashboard for Railway deployment
Runs the scan loop in background + serves the dashboard on PORT.
"""

import sys
import os
import asyncio
import threading

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from web.app import app
from core.engine import BotEngine


def run_bot():
    """Run the bot scan loop in a separate thread."""
    import traceback
    try:
        print("[BOT] Starting bot engine...", flush=True)
        engine = BotEngine(starting_capital=10_000.0)
        asyncio.run(engine.run())
    except Exception as e:
        print(f"[BOT] FATAL ERROR: {e}", flush=True)
        traceback.print_exc()


# Start bot in background thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

# Start web dashboard (Railway provides PORT env var)
port = int(os.environ.get("PORT", 8050))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=port)
else:
    # When Railway imports this module directly
    uvicorn.run(app, host="0.0.0.0", port=port)
