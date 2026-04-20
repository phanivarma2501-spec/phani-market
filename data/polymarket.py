import json
import requests
from typing import List, Dict, Optional
from settings import (
    POLYMARKET_GAMMA_URL, POLYMARKET_BASE_URL,
    MIN_LIQUIDITY_USD, MAX_MARKETS_PER_SCAN, MIN_ENTRY_PRICE,
    EXCLUDED_CATEGORIES,
)


# Polymarket's `category` field is almost always null, so EXCLUDED_CATEGORIES
# is mapped to question-text keywords here. Substring-matched case-insensitively.
_CATEGORY_KEYWORDS = {
    "gaming": [
        "counter-strike", "cs:go", "cs2", "league of legends", "lol:",
        "dota", "valorant", "overwatch", "starcraft", "fortnite",
        "call of duty", "apex legends", "hearthstone", "rocket league",
    ],
    "esports": ["esports", " lcs ", " lec ", " lck ", " lpl ", "worlds finals", " iem ", " esl "],
    "entertainment": [
        "oscar", "grammy", "emmy", "eurovision", "golden globe",
        "cannes", "box office", "academy award", "met gala",
    ],
    "tv": [
        "bachelor", "bachelorette", "survivor season", "big brother",
        "love island", "drag race", "real housewives", "dancing with",
        "the voice", "season finale", "tv show", "netflix series",
    ],
    "celebrity": [
        "kardashian", "kanye", "taylor swift", "beyonce", "rihanna",
        "drake", "nicki minaj", "celebrity",
    ],
    "reality": [
        "bachelor", "bachelorette", "survivor ", "big brother",
        "love island", "drag race", "real housewives", "reality tv",
        "reality show",
    ],
}


def _matches_excluded_category(question: str) -> Optional[str]:
    """Return the excluded category name if the question text matches any of its
    keywords; None otherwise. First match wins."""
    q = (question or "").lower()
    for category in EXCLUDED_CATEGORIES:
        keywords = _CATEGORY_KEYWORDS.get(category, [])
        if any(kw in q for kw in keywords):
            return category
    return None


def _parse_json_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def get_active_markets() -> List[Dict]:
    """Fetch active markets from Polymarket Gamma API."""
    try:
        params = {
            "active": "true",
            "closed": "false",
            "limit": 500,
            "order": "volume24hr",
            "ascending": "false"
        }
        resp = requests.get(f"{POLYMARKET_GAMMA_URL}/markets", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        filtered = []
        skipped_liquidity = skipped_no_date = skipped_parse = 0
        skipped_sports = skipped_extreme = skipped_category = 0
        for m in markets:
            try:
                # Polymarket's `category` field is almost always null — use sportsMarketType
                # (set to "moneyline"/"spread"/etc. on all sports markets) as the real signal.
                if m.get("sportsMarketType"):
                    skipped_sports += 1
                    continue
                # Keyword-based exclusion for EXCLUDED_CATEGORIES (gaming/esports/
                # entertainment/tv/celebrity/reality). Category field is null so we
                # pattern-match the question text.
                if _matches_excluded_category(m.get("question", "")):
                    skipped_category += 1
                    continue
                liquidity = float(m.get("liquidity") or 0)
                if liquidity < MIN_LIQUIDITY_USD:
                    skipped_liquidity += 1
                    continue
                end_date = m.get("endDate") or m.get("end_date")
                if not end_date:
                    skipped_no_date += 1
                    continue
                prices = _parse_json_list(m.get("outcomePrices"))
                yes_price = float(prices[0]) if len(prices) > 0 else 0.5
                no_price = float(prices[1]) if len(prices) > 1 else 1 - yes_price
                # Skip extreme markets pre-LLM: if either side is below MIN_ENTRY_PRICE,
                # the buy-side would be blocked in check_edge anyway and the other side
                # has ~zero edge room. Save the 2 LLM calls.
                if min(yes_price, no_price) < MIN_ENTRY_PRICE:
                    skipped_extreme += 1
                    continue
                filtered.append({
                    "id": str(m.get("id") or m.get("conditionId") or ""),
                    "conditionId": m.get("conditionId"),
                    "question": m.get("question", ""),
                    "category": m.get("category", "general"),
                    "end_date": end_date,
                    "liquidity_usd": liquidity,
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "volume_24hr": float(m.get("volume24hr") or 0),
                    "description": m.get("description", ""),
                })
            except Exception:
                skipped_parse += 1
                continue
        print(f"[Polymarket] {len(markets)} fetched | {len(filtered)} passed | "
              f"skipped: sports={skipped_sports}, category={skipped_category}, "
              f"liquidity={skipped_liquidity}, extreme={skipped_extreme}, "
              f"no_date={skipped_no_date}, parse={skipped_parse}")
        filtered.sort(key=lambda x: x["volume_24hr"], reverse=True)
        return filtered[:MAX_MARKETS_PER_SCAN]
    except Exception as e:
        print(f"[Polymarket] Error fetching markets: {e}")
        return []


def get_market_price(market_id: str) -> Optional[Dict]:
    """Get current YES/NO prices and closed state for a market."""
    try:
        resp = requests.get(f"{POLYMARKET_GAMMA_URL}/markets/{market_id}", timeout=10)
        resp.raise_for_status()
        m = resp.json()
        prices = _parse_json_list(m.get("outcomePrices"))
        yes = float(prices[0]) if len(prices) > 0 else 0.5
        no = float(prices[1]) if len(prices) > 1 else 1 - yes
        return {
            "yes_price": yes,
            "no_price": no,
            "closed": bool(m.get("closed", False)),
        }
    except Exception as e:
        print(f"[Polymarket] Error fetching price for {market_id}: {e}")
        return None
