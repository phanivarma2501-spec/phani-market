from settings import KELLY_FRACTION, MAX_POSITION_PCT, MIN_POSITION_USD, STARTING_BANKROLL


def calculate_kelly(
    probability: float,
    market_price: float,
    bankroll: float
) -> dict:
    """
    Calculate Kelly criterion bet size.

    probability: our estimated probability of YES
    market_price: current YES price (= implied probability)
    bankroll: current portfolio value

    Returns dict with fraction, size_usd, edge, direction
    """
    # Edge = our probability - market implied probability
    yes_edge = probability - market_price
    no_edge = (1 - probability) - (1 - market_price)

    # Determine direction
    if yes_edge > no_edge:
        direction = "YES"
        edge = yes_edge
        odds = (1 - market_price) / market_price  # Net odds for YES
        win_prob = probability
    else:
        direction = "NO"
        edge = no_edge
        odds = market_price / (1 - market_price)  # Net odds for NO
        win_prob = 1 - probability

    if edge <= 0:
        return {"direction": direction, "edge": edge, "kelly_fraction": 0, "size_usd": 0}

    # Full Kelly fraction: (p * odds - (1-p)) / odds
    full_kelly = (win_prob * odds - (1 - win_prob)) / odds

    # Apply fractional Kelly (quarter Kelly)
    fractional_kelly = full_kelly * KELLY_FRACTION

    # Cap at max position percentage
    capped_kelly = min(fractional_kelly, MAX_POSITION_PCT)
    capped_kelly = max(0, capped_kelly)

    # Calculate dollar size
    size_usd = bankroll * capped_kelly

    return {
        "direction": direction,
        "edge": edge,
        "yes_edge": yes_edge,
        "no_edge": no_edge,
        "kelly_fraction": capped_kelly,
        "full_kelly": full_kelly,
        "size_usd": size_usd,
        "odds": odds,
        "win_prob": win_prob,
    }
