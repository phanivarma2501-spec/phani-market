"""
server.py - Web dashboard + bot for Railway deployment
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from web.app import app

port = int(os.environ.get("PORT", 8050))
print(f"[SERVER] Starting on port {port}", flush=True)
uvicorn.run(app, host="0.0.0.0", port=port)
