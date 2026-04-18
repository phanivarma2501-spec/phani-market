"""Metaculus comparator — fuzzy-matches Polymarket questions to Metaculus
community forecasts. Returns a probability in [0, 1] only when we find a
confidently similar binary question; otherwise None (graceful degradation).
"""
import re
import requests
from typing import Optional
from settings import (
    METACULUS_BASE_URL, METACULUS_ENABLED, METACULUS_API_TOKEN,
    METACULUS_MATCH_THRESHOLD,
)


_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "will", "would", "have", "has", "had", "do", "does", "did", "of", "in",
    "on", "at", "to", "for", "with", "by", "from", "this", "that", "these",
    "those", "and", "or", "but", "not", "no", "what", "which", "who", "when",
    "where", "why", "how", "than", "then", "so", "if", "it", "its", "as",
}


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_community_probability(q: dict) -> Optional[float]:
    """Pull the binary YES-probability median out of a Metaculus question payload."""
    cp = q.get("community_prediction") or {}
    full = cp.get("full") or {}
    prob = full.get("q2")
    if prob is None:
        return None
    try:
        prob = float(prob)
    except (TypeError, ValueError):
        return None
    if 0.0 <= prob <= 1.0:
        return prob
    return None


def search_metaculus(question: str) -> Optional[float]:
    if not METACULUS_ENABLED:
        return None
    if not METACULUS_API_TOKEN:
        print("  [Metaculus] METACULUS_API_TOKEN not set — skipping")
        return None

    try:
        resp = requests.get(
            f"{METACULUS_BASE_URL}/questions/",
            params={"search": question, "status": "open", "limit": 8},
            headers={"Authorization": f"Token {METACULUS_API_TOKEN}"},
            timeout=10,
        )
    except Exception as e:
        print(f"  [Metaculus] Request error: {e}")
        return None

    if resp.status_code != 200:
        print(f"  [Metaculus] HTTP {resp.status_code}: {resp.text[:120]}")
        return None

    try:
        data = resp.json()
    except Exception:
        print("  [Metaculus] Non-JSON response")
        return None

    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None

    target = _tokens(question)
    best = None
    best_score = 0.0
    for q in results:
        # Binary-only — other question types don't have a single probability
        possibilities = (q.get("possibilities") or {}).get("type", "") or ""
        q_type = q.get("type") or ""
        if possibilities and possibilities != "binary":
            continue
        if q_type and "binary" not in q_type.lower() and q_type != "forecast":
            continue
        title = q.get("title") or q.get("title_short") or ""
        score = _jaccard(target, _tokens(title))
        if score > best_score:
            best_score = score
            best = q

    if best is None or best_score < METACULUS_MATCH_THRESHOLD:
        print(f"  [Metaculus] No match above threshold (best={best_score:.2f})")
        return None

    prob = _extract_community_probability(best)
    if prob is None:
        print(f"  [Metaculus] Match found (score={best_score:.2f}) but no community probability")
        return None

    title = (best.get("title") or "")[:60]
    print(f"  [Metaculus] Match {best_score:.2f} → {prob:.1%} on: {title}")
    return prob
