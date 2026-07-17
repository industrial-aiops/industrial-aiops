"""Waveform / vibration signal features — pure, stdlib-only, explainable.

For a fast-sampled waveform (accelerometer, current, pressure pulsation) the
*shape* of the signal carries condition information that a trend line cannot see:
a healthy bearing looks Gaussian, an early spall makes the signal **impulsive**
(kurtosis and crest factor climb well before RMS does). These are the classic,
textbook time-domain features — no ML, no FFT, each a few lines of arithmetic:

  * ``rms``               — AC RMS (mean removed) ≈ σ; overall energy/severity
  * ``peak``              — largest excursion from the mean
  * ``peak_to_peak``      — full span (max − min)
  * ``crest_factor``      — peak / rms; impulsiveness (rises with early defects)
  * ``kurtosis``          — excess (Fisher) kurtosis; ~0 Gaussian, >0 impulsive
  * ``zero_crossing_rate``— mean-crossings / (n−1); a coarse frequency proxy

Everything is **AC-coupled** (the DC/mean is removed first and reported
separately) so a sensor sitting at a large offset does not swamp the shape
metrics. The function refuses thin input and flags a flat signal instead of
dividing by a ~zero RMS. Pure: the input list is never mutated.
"""

from __future__ import annotations

from statistics import fmean

from iaiops.core.brain._shared import num
from iaiops.core.brain.pdm_math import mean_crossing_rate

MIN_FEATURE_SAMPLES = 8  # below this, feature statistics are noise → refuse
_ZERO_EPS = 1e-12


def waveform_features(values: list[float], min_samples: int = MIN_FEATURE_SAMPLES) -> dict:
    """[PURE] Time-domain shape features of a numeric waveform.

    ``values`` are plain numbers (already extracted from the series). Returns
    ``{status, ...}`` where status is ``insufficient_data`` (too few points),
    ``flat`` (no AC content — crest/kurtosis undefined, left as null), or ``ok``.
    Non-numeric entries are dropped (honest: only real samples are measured).
    """
    vals = [v for v in (num(x) for x in values) if v is not None]
    need = max(2, int(min_samples))
    n = len(vals)
    if n < need:
        return {
            "status": "insufficient_data",
            "samples": n,
            "needed": need,
            "note": f"Need >= {need} numeric samples for waveform features (got {n}).",
        }
    mean = fmean(vals)
    dev = [v - mean for v in vals]  # AC-couple: remove DC before shape math
    rms = _rms(dev)
    peak = max(abs(d) for d in dev)
    flat = rms < _ZERO_EPS
    return {
        "status": "flat" if flat else "ok",
        "samples": n,
        "mean": round(mean, 6),
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "peak_to_peak": round(max(vals) - min(vals), 6),
        "crest_factor": None if flat else round(peak / rms, 4),
        "kurtosis": _excess_kurtosis(dev, rms),
        "zero_crossing_rate": round(mean_crossing_rate(vals), 6),
        "note": (
            "AC-coupled (mean removed). rms≈σ (energy/severity); "
            "crest=peak/rms and kurtosis=excess (0≈Gaussian, >~1 impulsive, a "
            "bearing-fault early warning); zero_crossing_rate is a coarse "
            "frequency proxy. Meaningful for oscillatory/vibration signals — a "
            "near-monotonic trend yields large crest/kurtosis by construction "
            "(read pattern=gradual in that case, not a fault)."
        ),
    }


def _rms(dev: list[float]) -> float:
    """Root-mean-square of the (already mean-removed) deviations."""
    return (fmean([d * d for d in dev])) ** 0.5


def _excess_kurtosis(dev: list[float], rms: float) -> float | None:
    """Fisher excess kurtosis (m4 / m2² − 3); None when variance ~ 0 or n < 4."""
    if len(dev) < 4 or rms < _ZERO_EPS:
        return None
    m2 = fmean([d * d for d in dev])
    if m2 < _ZERO_EPS:
        return None
    m4 = fmean([d**4 for d in dev])
    return round(m4 / (m2 * m2) - 3.0, 4)


__all__ = ["waveform_features", "MIN_FEATURE_SAMPLES"]
