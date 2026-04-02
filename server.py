"""
server.py - Web dashboard + bot for Railway deployment
"""

import sys
import os
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fix Windows emoji encoding issue
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from loguru import logger

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/bot.log",
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
    encoding="utf-8",
)

import uvicorn
from web.app import app

port = int(os.environ.get("PORT", 8050))
logger.info(f"[SERVER] Starting on port {port}")
uvicorn.run(app, host="0.0.0.0", port=port)
