"""Metaculus integration — disabled.

The public API2 endpoint now 403s without an authenticated session.
Keeping the function signature so research.py imports stay stable;
re-enable by restoring a working fetch here.
"""
from typing import Optional


def search_metaculus(question: str) -> Optional[float]:
    return None
