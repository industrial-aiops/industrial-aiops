"""Drinking-water quality compliance — turbidity / chlorine / pH (pure).

The water-treatment operator's continuous-compliance question alongside the CT
disinfection calc: *are the finished-water parameters inside their limits?* From
per-sample readings it grades turbidity (a filtration-performance / pathogen
surrogate), free chlorine residual (too low = under-disinfected, too high = taste/
DBP), and pH against drinking-water limits — flagging any parameter out of range.

``water_quality_compliance`` is pure over injected readings; limits are
overridable (a utility sets its own permit values). Read-only and advisory, every
flag cited by its number.
"""

from __future__ import annotations

MAX_ROWS = 100

# Default finished-water limits. high=None ⇒ no upper bound; low=None ⇒ no lower.
_WQ_LIMITS: dict[str, dict] = {
    "turbidity_ntu": {"low": None, "high": 1.0, "unit": "NTU", "label": "turbidity"},
    "free_chlorine_mg_l": {"low": 0.2, "high": 4.0, "unit": "mg/L", "label": "free chlorine"},
    "ph": {"low": 6.5, "high": 8.5, "unit": "", "label": "pH"},
}


def water_quality_compliance(points: list[dict], limits: dict | None = None) -> dict:
    """[READ] Grade finished-water readings against drinking-water limits.

    ``points`` are ``{location, turbidity_ntu?, free_chlorine_mg_l?, ph?}`` — only
    the parameters present are graded. Defaults: turbidity ≤ 1.0 NTU, free chlorine
    0.2–4.0 mg/L, pH 6.5–8.5; pass ``limits`` (partial) to override per the permit.
    Each point takes the worst of its parameters (``breach`` when any is out of
    range), worst-first, citing every number. Pure, read-only, advisory.
    """
    active = _merge_limits(limits)
    graded = [_grade(p, active) for p in (points or []) if isinstance(p, dict)]
    summary: dict[str, int] = {}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    graded.sort(key=lambda g: (g["status"] != "breach", g["location"]))
    breaches = [g for g in graded if g["status"] == "breach"]
    return {
        "points_evaluated": len(graded),
        "limits": {k: {"low": v["low"], "high": v["high"]} for k, v in active.items()},
        "summary": summary,
        "breach_count": len(breaches),
        "breaches": breaches[:MAX_ROWS],
        "worst": breaches[0] if breaches else None,
    }


def _merge_limits(override: dict | None) -> dict:
    merged = {k: dict(v) for k, v in _WQ_LIMITS.items()}
    for key, bounds in (override or {}).items():
        if key in merged and isinstance(bounds, dict):
            merged[key].update({k: bounds[k] for k in ("low", "high") if k in bounds})
    return merged


def _grade(point: dict, limits: dict) -> dict:
    """Grade one sample point's provided parameters against the limits."""
    name = str(point.get("location") or point.get("name") or "?")
    flags: list[dict] = []
    for key, band in limits.items():
        value = point.get(key)
        if not isinstance(value, (int, float)):
            continue
        if band["low"] is not None and value < band["low"]:
            flags.append(_wq_flag(band, value, "low", band["low"]))
        elif band["high"] is not None and value > band["high"]:
            flags.append(_wq_flag(band, value, "high", band["high"]))
    status = "breach" if flags else ("compliant" if _has_reading(point, limits) else "no_data")
    return {"location": name, "status": status, "flags": flags}


def _wq_flag(band: dict, value: float, side: str, bound: float) -> dict:
    return {
        "parameter": band["label"],
        "value": value,
        "unit": band["unit"],
        "detail": f"{band['label']} {value}{band['unit']} is {side} of the "
        f"{bound}{band['unit']} limit",
    }


def _has_reading(point: dict, limits: dict) -> bool:
    return any(isinstance(point.get(k), (int, float)) for k in limits)


__all__ = ["water_quality_compliance", "MAX_ROWS"]
