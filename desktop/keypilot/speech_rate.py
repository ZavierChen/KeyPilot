"""Conservative user speed adjustment, relative to each voice's tuned baseline."""
import math

MIN_RATE = 0.90
MAX_RATE = 1.10
DEFAULT_RATE = 1.0


def clamp_rate(value) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return DEFAULT_RATE
    if not math.isfinite(number):
        return DEFAULT_RATE
    return round(max(MIN_RATE, min(MAX_RATE, number)), 2)
