"""Shared, explainable numeric primitives for the predictive-maintenance package.

Deliberately NOT a black box and dependency-free (stdlib only): a robust
**Theil–Sen** slope (median of pairwise slopes — resistant to spikes), its robust
intercept, a plain coefficient-of-determination (R²) so every fit can *state its
own quality*, a linear-interpolated percentile, and a mean-crossing rate. These
are the building blocks the forecast / RUL / degradation modules all reuse, kept
in one small module so the math is defined once and unit-tested in isolation.

Pure and immutable: inputs are never mutated; same inputs → same outputs.
"""

from __future__ import annotations

from statistics import fmean, median

_FLAT_EPS = 1e-9  # |slope| / variance below this is treated as flat/degenerate


def pairwise_slopes(xs: list[float], ys: list[float]) -> list[float]:
    """All finite pairwise slopes (dy/dx) — the sample behind a Theil–Sen fit.

    O(n²) in the number of points; callers bound ``n`` before calling. Pairs
    sharing an x (dx == 0) are skipped rather than dividing by zero.
    """
    slopes: list[float] = []
    n = len(xs)
    for i in range(n):
        xi, yi = xs[i], ys[i]
        for j in range(i + 1, n):
            dx = xs[j] - xi
            if dx != 0:
                slopes.append((ys[j] - yi) / dx)
    return slopes


def theil_sen(xs: list[float], ys: list[float]) -> float:
    """Median of the pairwise slopes (robust to outliers), 0.0 when undefined."""
    slopes = pairwise_slopes(xs, ys)
    return median(slopes) if slopes else 0.0


def robust_intercept(xs: list[float], ys: list[float], slope: float) -> float:
    """Median of ``y - slope·x`` — the Theil–Sen intercept (spike-resistant)."""
    if not xs:
        return 0.0
    return median([y - slope * x for x, y in zip(xs, ys)])


def r_squared(xs: list[float], ys: list[float], slope: float, intercept: float) -> float | None:
    """Coefficient of determination of ``slope·x + intercept`` over ``(xs, ys)``.

    Returns None when the data has ~no variance (R² undefined — an honest
    "cannot quantify fit" rather than a misleading 0 or 1). Clamped to ``>= 0``
    so a worse-than-mean model reports 0.0, never a negative surprise.
    """
    if len(ys) < 2:
        return None
    mean_y = fmean(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot < _FLAT_EPS:
        return None
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    return max(0.0, 1.0 - ss_res / ss_tot)


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (``pct`` in 0..100) over ``values``.

    Does not assume the input is sorted — sorts a copy (input untouched).
    """
    if not values:
        raise ValueError("cannot take a percentile of no values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (max(0.0, min(100.0, pct)) / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def mean_crossing_rate(values: list[float]) -> float:
    """Fraction of consecutive samples that cross the mean (0..1).

    A proxy for oscillation frequency: near 0 for a monotone trend, high for a
    fast alternating/cyclic signal. Computed about the mean so a DC offset does
    not suppress the count.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean = fmean(values)
    dev = [v - mean for v in values]
    crossings = sum(1 for a, b in zip(dev, dev[1:]) if (a > 0 and b < 0) or (a < 0 and b > 0))
    return crossings / (n - 1)


__all__ = [
    "pairwise_slopes",
    "theil_sen",
    "robust_intercept",
    "r_squared",
    "percentile",
    "mean_crossing_rate",
]
