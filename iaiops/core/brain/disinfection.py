"""Disinfection CT compliance — the water-treatment SWTR calc (pure).

The regulatory water-treatment question a generic threshold check can't answer:
*is the contact basin achieving enough disinfection credit?* Under the Surface
Water Treatment Rule, disinfection credit is measured as **CT** = disinfectant
residual concentration (mg/L) × effective contact time (T10, minutes). Achieved
CT is compared to the **required CT** for the target log-inactivation (which the
utility looks up from the state CT tables for its disinfectant, temperature and
pH) — the calc that says whether the water is adequately disinfected.

``disinfection_ct`` is pure over injected contact-basin readings; it does not
embed the CT tables (they are temperature/pH/disinfectant specific) — the caller
supplies ``required_ct`` from its own table. Read-only, advisory, every ratio
cited by its inputs.
"""

from __future__ import annotations

MAX_ROWS = 50


def disinfection_ct(points: list[dict], required_ct: float | None = None) -> dict:
    """[READ] Achieved CT vs required CT per contact basin (SWTR disinfection credit).

    ``points`` are ``{location, free_chlorine_mg_l, contact_time_min, baffle_factor?,
    required_ct?}`` — ``contact_time_min`` is the effective (T10) contact time;
    ``baffle_factor`` (T10/T, default 1.0) scales a theoretical detention time to
    T10 if you pass the theoretical time. Achieved CT = residual × time × baffle
    factor. Each point's achieved CT is compared to its ``required_ct`` (or the
    global one). Returns per-point CT ratios, worst-first, and whether every point
    meets its credit. Every number is cited.
    """
    rows = [_grade(p, required_ct) for p in (points or []) if isinstance(p, dict)]
    graded = [r for r in rows if r is not None]
    failing = [r for r in graded if r["status"] == "insufficient"]
    graded.sort(key=lambda r: (r["ctRatio"] is not None, r["ctRatio"] if r["ctRatio"] else 0))
    return {
        "points_evaluated": len(graded),
        "standard": "SWTR CT = residual (mg/L) × T10 (min); achieved ≥ required for the credit",
        "all_meet_credit": not failing,
        "failing_count": len(failing),
        "points": graded[:MAX_ROWS],
        "worst": graded[0] if graded else None,
    }


def _grade(point: dict, global_required: float | None) -> dict | None:
    """Compute one basin's achieved CT and compare to its required CT."""
    location = str(point.get("location") or point.get("name") or "?")
    residual = point.get("free_chlorine_mg_l", point.get("residual_mg_l"))
    t10 = point.get("contact_time_min", point.get("t10_min"))
    if not isinstance(residual, (int, float)) or not isinstance(t10, (int, float)):
        return {"location": location, "achievedCt": None, "requiredCt": None,
                "ctRatio": None, "status": "no_data",
                "detail": "missing free_chlorine_mg_l or contact_time_min"}
    baffle = point.get("baffle_factor", 1.0)
    baffle = float(baffle) if isinstance(baffle, (int, float)) else 1.0
    achieved = round(float(residual) * float(t10) * baffle, 3)

    required = point.get("required_ct", global_required)
    if not isinstance(required, (int, float)) or required <= 0:
        return {"location": location, "achievedCt": achieved, "requiredCt": None,
                "ctRatio": None, "status": "no_target",
                "detail": f"achieved CT {achieved} mg·min/L; no required_ct supplied to judge it"}

    ratio = round(achieved / float(required), 3)
    status = "adequate" if ratio >= 1.0 else "insufficient"
    detail = (f"achieved CT {achieved} vs required {required} mg·min/L "
              f"(ratio {ratio}) — {'meets' if status == 'adequate' else 'BELOW'} the credit")
    return {"location": location, "achievedCt": achieved, "requiredCt": float(required),
            "ctRatio": ratio, "status": status, "detail": detail}


__all__ = ["disinfection_ct", "MAX_ROWS"]
