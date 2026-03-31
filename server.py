"""
server.py - Combined bot + web dashboard for Railway deployment
Runs the scan loop in background + serves the dashboard on PORT.
"""

import asyncio
import os
import threading
import uvicorn
from web.app import app

# Import after setting PYTHONPATH
from core.engine import BotEngine


def run_bot():
    """Run the bot scan loop in a separate thread."""
    engine = BotEngine(starting_capital=10_000.0)
    asyncio.run(engine.run())


if __name__ == "__main__":
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Start web dashboard (Railway provides PORT env var)
    port = int(os.environ.get("PORT", 8050))
    uvicorn.run(app, host="0.0.0.0", port=port)
