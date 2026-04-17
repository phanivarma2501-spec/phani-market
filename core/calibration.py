import math
from settings import PLATT_SCALE


def calibrate(raw_probability: float) -> float:
    """
    Single-pass Platt scaling calibration.
    Compresses extreme probabilities toward base rates.
    No stacking — this is the ONLY calibration step.
    """
    if raw_probability is None:
        return None

    # Clamp input
    p = max(0.01, min(0.99, raw_probability))

    # Convert to log-odds
    log_odds = math.log(p / (1 - p))

    # Apply Platt scaling (single pass)
    scaled_log_odds = log_odds * PLATT_SCALE

    # Convert back to probability
    calibrated = 1 / (1 + math.exp(-scaled_log_odds))

    # Final clamp
    return max(0.01, min(0.99, calibrated))


def calculate_brier_score(predicted: float, actual: float) -> float:
    """Calculate Brier score for a resolved prediction. Lower is better."""
    return (predicted - actual) ** 2


def apply_metaculus_adjustment(
    calibrated_prob: float,
    metaculus_prob: float,
    gap_threshold: float = 0.10
) -> tuple:
    """
    If Metaculus disagrees with market by more than gap_threshold,
    blend Metaculus probability into our estimate.
    Returns (adjusted_probability, metaculus_signal_used)
    """
    if metaculus_prob is None:
        return calibrated_prob, False

    gap = abs(metaculus_prob - calibrated_prob)

    if gap >= gap_threshold:
        # Blend: 60% our estimate, 40% Metaculus
        adjusted = 0.6 * calibrated_prob + 0.4 * metaculus_prob
        return adjusted, True

    return calibrated_prob, False
