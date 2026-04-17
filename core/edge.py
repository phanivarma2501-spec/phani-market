from settings import EDGE_THRESHOLD_BUY, EDGE_THRESHOLD_STRONG, MIN_POSITION_USD, MIN_ENTRY_PRICE


def check_edge(kelly_result: dict, size_usd: float, entry_price: float) -> dict:
    """
    Gate: only allow bets that meet minimum edge threshold.
    Returns dict with should_bet, reason, signal_strength.
    """
    edge = kelly_result.get("edge", 0)
    direction = kelly_result.get("direction", "YES")

    # Longshot filter: skip bets on sub-5% entry prices (LLM hallucinates on dead markets)
    if entry_price < MIN_ENTRY_PRICE:
        return {
            "should_bet": False,
            "reason": f"Entry price too low ({entry_price:.3f} < {MIN_ENTRY_PRICE:.2f})",
            "signal_strength": "none"
        }

    # Minimum size check
    if size_usd < MIN_POSITION_USD:
        return {
            "should_bet": False,
            "reason": f"Position too small (${size_usd:.2f} < ${MIN_POSITION_USD})",
            "signal_strength": "none"
        }

    # Edge threshold checks
    if edge >= EDGE_THRESHOLD_STRONG:
        return {
            "should_bet": True,
            "reason": f"Strong edge detected: {edge:.1%} on {direction}",
            "signal_strength": "strong"
        }
    elif edge >= EDGE_THRESHOLD_BUY:
        return {
            "should_bet": True,
            "reason": f"Edge detected: {edge:.1%} on {direction}",
            "signal_strength": "normal"
        }
    else:
        return {
            "should_bet": False,
            "reason": f"Edge too small: {edge:.1%} (minimum: {EDGE_THRESHOLD_BUY:.1%})",
            "signal_strength": "none"
        }


def check_exit(current_probability: float, direction: str, entry_price: float) -> dict:
    """
    Determine if an open position should be exited.
    Exit when our edge has dropped below EXIT_EDGE_THRESHOLD.
    """
    from settings import EXIT_EDGE_THRESHOLD

    if direction == "YES":
        current_edge = current_probability - entry_price
    else:
        current_edge = (1 - current_probability) - (1 - entry_price)

    if current_edge < EXIT_EDGE_THRESHOLD:
        return {
            "should_exit": True,
            "reason": f"Edge dropped to {current_edge:.1%} (threshold: {EXIT_EDGE_THRESHOLD:.1%})"
        }

    return {
        "should_exit": False,
        "reason": f"Edge still healthy at {current_edge:.1%}"
    }
