import json
import requests
from typing import List, Dict, Optional
from settings import POLYMARKET_GAMMA_URL, POLYMARKET_BASE_URL, MIN_LIQUIDITY_USD, MAX_MARKETS_PER_SCAN


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
            "limit": 100,
            "order": "volume24hr",
            "ascending": "false"
        }
        resp = requests.get(f"{POLYMARKET_GAMMA_URL}/markets", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        filtered = []
        skipped_liquidity = skipped_no_date = skipped_parse = 0
        for m in markets:
            try:
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
              f"skipped: liquidity={skipped_liquidity}, no_date={skipped_no_date}, parse={skipped_parse}")
        filtered.sort(key=lambda x: x["volume_24hr"], reverse=True)
        return filtered[:MAX_MARKETS_PER_SCAN]
    except Exception as e:
        print(f"[Polymarket] Error fetching markets: {e}")
        return []


def get_market_price(market_id: str) -> Optional[Dict]:
    """Get current YES/NO prices for a market."""
    try:
        resp = requests.get(f"{POLYMARKET_GAMMA_URL}/markets/{market_id}", timeout=10)
        resp.raise_for_status()
        m = resp.json()
        prices = _parse_json_list(m.get("outcomePrices"))
        yes = float(prices[0]) if len(prices) > 0 else 0.5
        no = float(prices[1]) if len(prices) > 1 else 1 - yes
        return {"yes_price": yes, "no_price": no}
    except Exception as e:
        print(f"[Polymarket] Error fetching price for {market_id}: {e}")
        return None
