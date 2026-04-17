import requests
from typing import List, Dict, Optional
from settings import POLYMARKET_GAMMA_URL, POLYMARKET_BASE_URL, MIN_LIQUIDITY_USD, MAX_MARKETS_PER_SCAN


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
        for m in markets:
            try:
                liquidity = float(m.get("liquidity", 0) or 0)
                if liquidity < MIN_LIQUIDITY_USD:
                    continue
                # Skip markets with no clear end date
                if not m.get("endDate") and not m.get("end_date"):
                    continue
                filtered.append({
                    "id": str(m.get("id", m.get("conditionId", ""))),
                    "question": m.get("question", ""),
                    "category": m.get("category", "general"),
                    "end_date": m.get("endDate") or m.get("end_date"),
                    "liquidity_usd": liquidity,
                    "yes_price": float(m.get("outcomePrices", ["0.5"])[0] if m.get("outcomePrices") else 0.5),
                    "no_price": float(m.get("outcomePrices", ["0.5", "0.5"])[1] if m.get("outcomePrices") else 0.5),
                    "volume_24hr": float(m.get("volume24hr", 0) or 0),
                    "description": m.get("description", ""),
                })
            except Exception:
                continue
        # Sort by volume and take top N
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
        return {
            "yes_price": float(m.get("outcomePrices", ["0.5"])[0] if m.get("outcomePrices") else 0.5),
            "no_price": float(m.get("outcomePrices", ["0.5", "0.5"])[1] if m.get("outcomePrices") else 0.5),
        }
    except Exception as e:
        print(f"[Polymarket] Error fetching price for {market_id}: {e}")
        return None
