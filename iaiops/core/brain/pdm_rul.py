"""Remaining-useful-life (RUL) estimation — extrapolate degradation to a limit.

The base forecast already gives a single linear ETA. This deepens it into an
*honest* RUL estimate:

  * a **confidence band** on the ETA, derived from the inter-quartile spread of
    the pairwise Theil–Sen slopes — a wide slope spread ⇒ a wide ETA band ⇒ low
    confidence, stated explicitly (no false precision);
  * a **fit quality** (R²) for the linear model, so the estimate carries its own
    trustworthiness;
  * an **exponential** alternative (``y = a·e^{bτ}``) fitted robustly in log
    space, for compounding degradation that a straight line under-warns; the two
    models are compared on the SAME raw-space R² and the better fit is
    recommended, with the reason spelled out.

If the slope spread straddles zero, or values are non-positive (no log), or the
limit is not ahead on the fitted curve, the module says so instead of inventing
a number. Pure and stdlib-only.
"""

from __future__ import annotations

import math
from statistics import fmean, median

from iaiops.core.brain._shared import s
from iaiops.core.brain.pdm_math import (
    pairwise_slopes,
    percentile,
    r_squared,
    robust_intercept,
)

_FLAT_EPS = 1e-9


def estimate_rul(
    xs: list[float],
    values: list[float],
    slopes: list[float],
    current: float,
    limit_name: str,
    limit_val: float,
    unit: str,
) -> dict:
    """[PURE] Linear + exponential RUL to ``limit_val`` with a confidence band.

    ``slopes`` are the already-computed pairwise slopes (reused, not recomputed).
    Returns a block describing both models, the ETA band, the recommended model,
    and an explicit confidence label + rationale. ETA is in ``unit`` (s|samples).
    """
    slope = median(slopes) if slopes else 0.0
    intercept = robust_intercept(xs, values, slope)
    lin_r2 = r_squared(xs, values, slope, intercept)
    band = _eta_band(slopes, current, limit_val)
    exp = _exp_rul(xs, values, limit_val)
    linear = {
        "eta": round((limit_val - current) / slope, 2) if abs(slope) > _FLAT_EPS else None,
        "r_squared": None if lin_r2 is None else round(lin_r2, 4),
    }
    recommended, why = _pick_model(lin_r2, exp)
    confidence, rationale = _confidence(lin_r2, band)
    return {
        "unit": unit,
        "target": {"name": s(limit_name, 20), "value": limit_val},
        "linear": linear,
        "exponential": exp,
        "eta_band": band,
        "recommended_model": recommended,
        "recommended_reason": why,
        "confidence": confidence,
        "confidence_rationale": rationale,
    }


def _eta_band(slopes: list[float], current: float, limit_val: float) -> dict | None:
    """ETA range from the p25/p75 slopes — None if the spread straddles zero."""
    if not slopes:
        return None
    lo_slope = percentile(slopes, 25.0)
    hi_slope = percentile(slopes, 75.0)
    etas: list[float] = []
    for sl in (lo_slope, hi_slope):
        if abs(sl) < _FLAT_EPS:
            continue
        eta = (limit_val - current) / sl
        if eta > 0:  # slope points toward the limit
            etas.append(eta)
    if len(etas) < 2:  # spread straddles zero → cannot bound the ETA honestly
        return None
    return {
        "low": round(min(etas), 2),
        "high": round(max(etas), 2),
        "basis": "IQR (p25..p75) of pairwise Theil-Sen slopes",
    }


def _exp_rul(xs: list[float], values: list[float], limit_val: float) -> dict:
    """Robust exponential fit ``y = a·e^{bτ}`` (log space) and its ETA to limit."""
    if any(v <= 0 for v in values):
        return {"status": "not_applicable", "reason": "needs strictly positive values (log)"}
    if limit_val <= 0:
        return {"status": "not_applicable", "reason": "limit must be positive for a log model"}
    t0 = xs[0]
    tau = [x - t0 for x in xs]
    logs = [math.log(v) for v in values]
    b_slopes = pairwise_slopes(tau, logs)
    b = median(b_slopes) if b_slopes else 0.0
    if abs(b) < _FLAT_EPS:
        return {"status": "not_applicable", "reason": "no exponential growth/decay detected"}
    ln_a = robust_intercept(tau, logs, b)
    r2 = _exp_r_squared(tau, values, ln_a, b)
    eta = (math.log(limit_val) - ln_a) / b - tau[-1]
    r2_out = None if r2 is None else round(r2, 4)
    if not math.isfinite(eta) or eta <= 0:
        return {
            "status": "unreachable",
            "reason": "limit not ahead on the fitted curve",
            "r_squared": r2_out,
        }
    return {"status": "ok", "eta": round(eta, 2), "rate_per_unit": round(b, 9), "r_squared": r2_out}


def _exp_r_squared(tau: list[float], values: list[float], ln_a: float, b: float) -> float | None:
    """R² of the exponential fit in RAW space (comparable to the linear R²)."""
    if len(values) < 2:
        return None
    mean_y = fmean(values)
    ss_tot = sum((v - mean_y) ** 2 for v in values)
    if ss_tot < _FLAT_EPS:
        return None
    ss_res = 0.0
    for t, v in zip(tau, values):
        pred = math.exp(ln_a + b * t)
        if not math.isfinite(pred):
            return None
        ss_res += (v - pred) ** 2
    return max(0.0, 1.0 - ss_res / ss_tot)


def _pick_model(lin_r2: float | None, exp: dict) -> tuple[str, str]:
    """Recommend the better-fitting model on raw-space R², explaining why."""
    exp_r2 = exp.get("r_squared") if exp.get("status") == "ok" else None
    if lin_r2 is None and exp_r2 is None:
        return "unknown", "neither fit is quantifiable (near-constant series)"
    if exp_r2 is None:
        return "linear", f"exponential model not usable ({exp.get('reason', 'n/a')})"
    if lin_r2 is None:
        return "exponential", "linear fit not quantifiable"
    if exp_r2 > lin_r2 + 0.02:  # require a real margin before preferring the curve
        return "exponential", f"exponential fits better (R^2 {exp_r2} vs {round(lin_r2, 4)})"
    return "linear", f"linear fits at least as well (R^2 {round(lin_r2, 4)} vs {exp_r2})"


def _confidence(lin_r2: float | None, band: dict | None) -> tuple[str, str]:
    """Qualitative confidence in the ETA, from fit quality and band width."""
    if lin_r2 is None:
        return "low", "fit quality not quantifiable (near-constant series)"
    if band is None:
        return "low", "slope spread straddles zero — direction of travel is not robust"
    high = band["high"]
    width_ratio = (high - band["low"]) / high if high > _FLAT_EPS else 1.0
    r2 = round(lin_r2, 4)
    pct = round(width_ratio * 100)
    if lin_r2 >= 0.9 and width_ratio <= 0.5:
        return "high", f"tight linear fit (R^2={r2}); ETA band {pct}% of the high estimate"
    if lin_r2 >= 0.6:
        return "medium", f"moderate linear fit (R^2={r2}); ETA band {pct}% of the high estimate"
    return "low", f"weak linear fit (R^2={r2}) — treat the ETA as indicative only"


__all__ = ["estimate_rul"]
