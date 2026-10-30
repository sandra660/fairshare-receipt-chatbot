"""Exact money arithmetic.

Money is handled in whole minor units (piasters / cents) as integers, never floats:
0.1 + 0.2 != 0.3 in floating point, and a bill split must add up to the receipt total exactly.
"""
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: float | int | str) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> float:
    return cents / 100


def fmt(cents: int, currency: str = "EGP") -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) / 100:,.2f} {currency}"


def allocate(total_cents: int, weights: dict[str, float]) -> dict[str, int]:
    """Split an amount by weights so that the parts add up EXACTLY to the total.

    Largest-remainder method: give everyone the rounded-down share, then hand the leftover
    cents one by one to whoever lost the most in rounding.
    Example: allocate(1000, {"A": 1, "B": 1, "C": 1}) -> {"A": 334, "B": 333, "C": 333}
    """
    weights = {k: w for k, w in weights.items() if w > 0}
    if not weights:
        return {}
    weight_sum = sum(weights.values())
    sign = -1 if total_cents < 0 else 1
    remaining = abs(total_cents)

    exact = {k: remaining * w / weight_sum for k, w in weights.items()}
    parts = {k: int(v) for k, v in exact.items()}
    leftover = remaining - sum(parts.values())
    by_remainder = sorted(exact, key=lambda k: -(exact[k] - parts[k]))  # stable: ties keep the original order
    for k in by_remainder[:leftover]:
        parts[k] += 1
    return {k: sign * v for k, v in parts.items()}
