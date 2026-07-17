"""Degradation-pattern classification — gradual vs sudden vs cyclic, explained.

Two signals with the same trend slope can fail for very different reasons: a
bearing wearing **gradually**, a coupling that **suddenly** steps to a new level,
or a **cyclic** load that never really drifts. Naming the pattern tells the
operator whether an ETA is even meaningful (a step change has no smooth ETA; a
cyclic signal is not "degrading" at all).

The classifier is a small set of transparent, bounded scores — no ML:

  * ``monotonicity``    — share of consecutive steps in the dominant direction
    (0.5 = coin-flip, 1.0 = never reverses); ~1 ⇒ a smooth ramp (linear OR
    curved), the primary "gradual" signal;
  * ``trend_fraction``  — how much of the span the linear trend explains
    (|slope|·(n−1) / peak-to-peak); ~1 ⇒ a *straight* ramp;
  * ``residual_ratio``  — leftover scatter after detrending / raw scatter;
    low ⇒ the line explains the data, high ⇒ something else does;
  * ``oscillation_rate``— mean-crossings of the residual (a frequency proxy);
  * ``step_score``      — best two-segment level separation in units of within-
    segment spread (a Cohen's-d-like statistic); high + localized ⇒ a step.

Each verdict cites these metrics so the call is auditable. Pure/stdlib-only;
gradual patterns also report a shape (accelerating/steady/decelerating) and
cyclic patterns an approximate period from autocorrelation.
"""

from __future__ import annotations

from statistics import fmean, median, pstdev

from iaiops.core.brain.pdm_math import (
    mean_crossing_rate,
    pairwise_slopes,
    robust_intercept,
)

DEGRADE_MIN_SAMPLES = 12  # below this, a pattern call would be guesswork → unknown
_FLAT_EPS = 1e-9

# Decision thresholds (transparent, tunable knobs — not magic).
_STEP_STRONG = 6.0  # a level jump this many within-segment spreads ⇒ a clean step
_STEP_RESID = 0.4  # ...AND the trend leaves this much scatter (step isn't a ramp)
_CYCLIC_MAX_TREND = 0.4  # a cycle has little net drift (else it is a mixed signal)
_MONO_CLEAN = 0.8  # this share of steps in one direction ⇒ a smooth ramp
_PERIOD_MIN_AC = 0.5  # autocorrelation peak this strong ⇒ a real repeating cycle


def classify_degradation(values: list[float], min_samples: int = DEGRADE_MIN_SAMPLES) -> dict:
    """[PURE] Label a value series' degradation pattern with cited metrics.

    Returns ``{pattern, samples, confidence, rationale, metrics{...}}`` where
    pattern is ``unknown`` (too few samples), ``flat`` (no movement),
    ``gradual``, ``sudden``, ``cyclic``, or ``irregular`` (no single mode
    dominates — an honest "mixed" verdict rather than a forced label).
    """
    vals = [float(v) for v in values]
    need = max(4, int(min_samples))
    n = len(vals)
    if n < need:
        return {
            "pattern": "unknown",
            "samples": n,
            "note": f"Need >= {need} samples to classify degradation (got {n}).",
        }
    p2p = max(vals) - min(vals)
    raw_sd = pstdev(vals)
    if p2p < _FLAT_EPS or raw_sd < _FLAT_EPS:
        return _verdict(
            "flat", n, "high", "no measurable movement across the window", _zero_metrics()
        )

    xs = [float(i) for i in range(n)]
    slope = median(pairwise_slopes(xs, vals) or [0.0])
    intercept = robust_intercept(xs, vals, slope)
    resid = [v - (slope * i + intercept) for i, v in enumerate(vals)]
    step = _best_step(vals)
    period = _dominant_period(resid)
    metrics = {
        "monotonicity": round(_monotonicity(vals), 4),
        "trend_fraction": round(min(1.0, abs(slope) * (n - 1) / p2p), 4),
        "residual_ratio": round(pstdev(resid) / raw_sd, 4) if raw_sd else 0.0,
        "oscillation_rate": round(mean_crossing_rate(resid), 4),
        "step_score": round(step["score"], 4),
    }
    pattern, confidence, rationale = _decide(metrics, period is not None)
    verdict = _verdict(pattern, n, confidence, rationale, metrics)
    return {**verdict, **_pattern_extra(pattern, xs, vals, step, period)}


def _decide(m: dict, has_period: bool) -> tuple[str, str, str]:
    """Pick the dominant pattern from the scores + periodicity, in priority order.

    Cyclic is tested first (an oscillation with a real autocorrelation peak is not
    a trend, whatever its slope looks like); then a *localized, strong* level step
    (high step_score AND scatter the trend cannot explain); then a clean ramp;
    else an honest ``irregular`` (mixed/noisy — no forced label).
    """
    mono, tf, rr, zcr, step = (
        m["monotonicity"],
        m["trend_fraction"],
        m["residual_ratio"],
        m["oscillation_rate"],
        m["step_score"],
    )
    if has_period and tf < _CYCLIC_MAX_TREND:
        return (
            "cyclic",
            "high" if tf < 0.2 else "medium",
            (
                f"a repeating cycle (strong autocorrelation peak past the first "
                f"zero-crossing) with little net drift (trend_fraction={tf}, "
                f"oscillation_rate={zcr})"
            ),
        )
    if step >= _STEP_STRONG and rr >= _STEP_RESID:
        return (
            "sudden",
            "high" if step >= _STEP_STRONG * 1.5 else "medium",
            (
                f"a localized level step dominates (step_score={step} in within-segment "
                f"spread) and the trend cannot explain it (residual_ratio={rr})"
            ),
        )
    if mono >= _MONO_CLEAN:
        return (
            "gradual",
            "high" if mono >= 0.95 and rr <= 0.4 else "medium",
            (
                f"a smooth monotone trend ({round(mono * 100)}% of steps in one "
                f"direction; trend_fraction={tf}, residual_ratio={rr})"
            ),
        )
    return (
        "irregular",
        "low",
        (
            f"no single mode dominates (monotonicity={mono}, trend_fraction={tf}, "
            f"residual_ratio={rr}, oscillation_rate={zcr}, step_score={step}) — "
            f"treat as mixed/noisy"
        ),
    )


def _monotonicity(vals: list[float]) -> float:
    """Share of consecutive steps in the dominant direction (0.5..1.0).

    Ties (exactly equal successive samples) are ignored. 1.0 = never reverses (a
    clean ramp, linear or curved); ~0.5 = a coin-flip (noise or oscillation).
    """
    nz = [b - a for a, b in zip(vals, vals[1:]) if b != a]
    if not nz:
        return 1.0
    up = sum(1 for d in nz if d > 0) / len(nz)
    return max(up, 1.0 - up)


def _best_step(vals: list[float]) -> dict:
    """Best two-segment split by level separation / within-segment spread.

    Cohen's-d-like: a genuine level shift separates the segment means by many
    within-segment standard deviations (high score); a smooth ramp grows the
    within-segment spread too, keeping the score modest.
    """
    n = len(vals)
    best = {"score": 0.0, "index": None}
    for k in range(2, n - 1):
        left, right = vals[:k], vals[k:]
        separation = abs(fmean(right) - fmean(left))
        spread = (pstdev(left) + pstdev(right)) / 2.0
        score = separation / spread if spread > _FLAT_EPS else separation / _FLAT_EPS
        if score > best["score"]:
            best = {"score": score, "index": k}
    return best


def _pattern_extra(
    pattern: str, xs: list[float], vals: list[float], step: dict, period: int | None
) -> dict:
    """Per-pattern detail: ramp shape, step location, or cyclic period (reused)."""
    if pattern == "gradual":
        return {"shape": _trend_shape(xs, vals)}
    if pattern == "sudden":
        return {"step_at_sample": step["index"]}
    if pattern == "cyclic" and period:
        return {"approx_period_samples": period}
    return {}


def _trend_shape(xs: list[float], vals: list[float]) -> str:
    """Compare the early-third and late-third slopes of a monotone trend."""
    n = len(vals)
    k = max(2, n // 3)
    early = median(pairwise_slopes(xs[:k], vals[:k]) or [0.0])
    late = median(pairwise_slopes(xs[-k:], vals[-k:]) or [0.0])
    if abs(early) < _FLAT_EPS and abs(late) < _FLAT_EPS:
        return "steady"
    if early * late < 0:
        return "reversing"
    if abs(late) > abs(early) * 1.3:
        return "accelerating"
    if abs(late) < abs(early) * 0.7:
        return "decelerating"
    return "steady"


def _dominant_period(series: list[float]) -> int | None:
    """Period (samples) of a real cycle, or None — the textbook ACF method.

    Normalized autocorrelation is scanned only AFTER its first descent below zero:
    that skips the trivial small-lag correlation of any smooth signal (a
    monotone ramp or single arch never rebounds to a strong peak), so only a
    genuinely *repeating* signal yields a peak >= ``_PERIOD_MIN_AC``. Returns the
    lag of that peak.
    """
    n = len(series)
    if n < 6:
        return None
    mean = fmean(series)
    dev = [v - mean for v in series]
    denom = sum(d * d for d in dev)
    if denom < _FLAT_EPS:
        return None
    crossed = False
    best_lag, best_ac = None, 0.0
    for lag in range(1, n // 2 + 1):
        ac = sum(dev[i] * dev[i + lag] for i in range(n - lag)) / denom
        if not crossed:
            if ac < 0.0:  # wait for the first zero-crossing before hunting a peak
                crossed = True
            continue
        if ac > best_ac:
            best_ac, best_lag = ac, lag
    return best_lag if (best_lag is not None and best_ac >= _PERIOD_MIN_AC) else None


def _verdict(pattern: str, n: int, confidence: str, rationale: str, metrics: dict) -> dict:
    return {
        "pattern": pattern,
        "samples": n,
        "confidence": confidence,
        "rationale": rationale,
        "metrics": metrics,
    }


def _zero_metrics() -> dict:
    return {
        "monotonicity": 1.0,
        "trend_fraction": 0.0,
        "residual_ratio": 0.0,
        "oscillation_rate": 0.0,
        "step_score": 0.0,
    }


__all__ = ["classify_degradation", "DEGRADE_MIN_SAMPLES"]
