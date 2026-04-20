"""
Topic-bucket correlation cap.

Purpose: the top-25 Polymarket universe is dominated by a few topic clusters
(Iran/Israel ~50%, sports futures ~25%). Without a cap, filling MAX_OPEN_POSITIONS
slots almost always produces a heavily correlated book. Quarter-Kelly assumes
independent bets; correlation amplifies drawdowns.

Approach: classify each market into one topic bucket via keyword match.
Enforce BUCKET_CAP concurrent open positions per bucket. 'other' has no cap.

Buckets are iterated in order — first match wins. Put more specific / more
newsworthy topics earlier so e.g. 'US x Iran peace deal' is iran_middle_east,
not us_politics.
"""

from collections import Counter
from typing import Iterable, List, Optional, Tuple

BUCKET_CAP = 3

BUCKETS: List[Tuple[str, List[str]]] = [
    ("iran_middle_east", [
        "iran", "israel", "hezbollah", "hormuz", "kharg", "gaza", "houthi",
        "palestin", "tehran", "netanyahu",
    ]),
    ("crypto", [
        "bitcoin", "btc", "ethereum", " eth ", "solana", " sol ", "crypto",
        "xrp", "dogecoin", "stablecoin",
    ]),
    ("sports_futures", [
        "world cup", "nba finals", "nba mvp", "champions league", "premier league",
        "la liga", "bundesliga", "serie a", "stanley cup", "super bowl",
        "world series", "masters tournament", "wimbledon",
    ]),
    ("entertainment", [
        "bachelor", "bachelorette", "taylor swift", "kim kardashian",
        "oscar", "grammy", "eurovision", "dancing with", "kanye",
    ]),
    ("us_politics", [
        "rubio", "vance", "fed chair", "biden", "harris", "trump",
        "supreme court", "us presidential", "us senate", "us house",
        "gop ", "democrat", "republican", "speaker of the house",
    ]),
]


def classify(question: str) -> str:
    """Return the first matching bucket name, or 'other' if no keywords hit."""
    q = (question or "").lower()
    for name, keywords in BUCKETS:
        if any(kw in q for kw in keywords):
            return name
    return "other"


def count_buckets(questions: Iterable[str]) -> Counter:
    """Bucket-counts for a collection of question strings."""
    return Counter(classify(q) for q in questions)


def blocked_reason(bucket: str, counts: Counter) -> Optional[str]:
    """Return a human-readable block reason if `bucket` would exceed cap, else None."""
    if bucket == "other":
        return None
    if counts.get(bucket, 0) >= BUCKET_CAP:
        return f"{bucket} bucket at cap ({BUCKET_CAP})"
    return None
