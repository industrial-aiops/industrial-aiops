"""Air-handler economizer fault detection (pure).

The building-energy question generic threshold checks miss: *is the air handler
using free cooling when it could, and not fighting itself?* From an AHU's air
temperatures and states it flags the classic economizer faults a building
analytics (FDD) tool looks for:

  * **simultaneous heat/cool** — heating and mechanical cooling both on (pure waste).
  * **not economizing** — outside air is cool enough for free cooling, yet the
    economizer damper is at minimum and mechanical cooling is running.
  * **economizing when it shouldn't** — outside air is above the high limit, yet
    the damper is wide open (dragging hot/humid air in).

Pure function over injected AHU readings; read-only and advisory, each fault
cited by the temperatures/states behind it.
"""

from __future__ import annotations

MAX_ROWS = 100

# Defaults: free cooling is useful when OAT is at least this far below RAT; a
# damper at/below this % is "at minimum"; the economizer high limit (lockout).
DEFAULT_FREE_COOL_DELTA_C = 2.0
DEFAULT_MIN_DAMPER_PCT = 15.0
DEFAULT_HIGH_LIMIT_C = 18.0


def economizer_check(
    units: list[dict],
    free_cool_delta_c: float = DEFAULT_FREE_COOL_DELTA_C,
    min_damper_pct: float = DEFAULT_MIN_DAMPER_PCT,
    high_limit_c: float = DEFAULT_HIGH_LIMIT_C,
) -> dict:
    """[READ] Detect economizer faults across air handlers.

    ``units`` are ``{ahu, oat_c, rat_c, oa_damper_pct?, mech_cooling?, heating?}``.
    Flags simultaneous heat/cool, not-economizing (free cooling available but the
    damper is at minimum while mechanical cooling runs), and economizing-when-
    locked-out (OAT above the high limit but the damper wide open). Worst-first,
    each fault citing the temperatures/states behind it. Pure, read-only, advisory.
    """
    graded = [
        _grade(u, free_cool_delta_c, min_damper_pct, high_limit_c)
        for u in (units or []) if isinstance(u, dict)
    ]
    summary: dict[str, int] = {}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    graded.sort(key=lambda g: (g["status"] == "ok", g["status"] == "no_data", g["ahu"]))
    faults = [g for g in graded if g["status"] not in ("ok", "no_data")]
    return {
        "units_evaluated": len(graded),
        "summary": summary,
        "fault_count": len(faults),
        "faults": faults[:MAX_ROWS],
        "worst": faults[0] if faults else None,
        "note": (
            "Advisory economizer FDD over injected AHU readings; each fault cites "
            "the temperatures/states behind it. Confirm sensor calibration and "
            "damper feedback before dispatching."
        ),
    }


def _grade(unit: dict, delta: float, min_damper: float, high_limit: float) -> dict:
    """Classify one AHU's economizer behaviour."""
    ahu = str(unit.get("ahu") or unit.get("name") or "?")
    oat = unit.get("oat_c")
    rat = unit.get("rat_c")
    damper = unit.get("oa_damper_pct")
    cooling = bool(unit.get("mech_cooling", False))
    heating = bool(unit.get("heating", False))

    if heating and cooling:
        return _f(ahu, "simultaneous_heat_cool",
                  "heating and mechanical cooling are both ON — pure energy waste")
    if not isinstance(oat, (int, float)):
        return _f(ahu, "no_data", "no outside-air temperature reading")

    free_cooling_available = isinstance(rat, (int, float)) and oat <= rat - delta
    if free_cooling_available and cooling and _at_min(damper, min_damper):
        return _f(ahu, "not_economizing",
                  f"OAT {oat}°C is {round(rat - oat, 1)}°C below RAT {rat}°C (free cooling "
                  f"available) but the OA damper is at minimum while mechanical cooling runs")
    if oat > high_limit and isinstance(damper, (int, float)) and damper > min_damper:
        return _f(ahu, "economizing_when_locked_out",
                  f"OAT {oat}°C is above the {high_limit}°C high limit but the OA damper "
                  f"is open ({damper}%) — dragging hot air in")
    return _f(ahu, "ok", "economizer behaviour consistent with the air temperatures")


def _at_min(damper: object, min_damper: float) -> bool:
    # Treat an unknown damper as "at minimum" only implicitly avoided: require a reading.
    return isinstance(damper, (int, float)) and damper <= min_damper


def _f(ahu: str, status: str, detail: str) -> dict:
    return {"ahu": ahu, "status": status, "detail": detail}


# ── Zone comfort + indoor air quality (ASHRAE 55 / 62.1) ─────────────────────
# Default acceptable ranges for an occupied zone. high=None ⇒ no upper bound.
_COMFORT_PARAMS: dict[str, dict] = {
    "temp_c": {"low": 20.0, "high": 26.0, "unit": "°C", "label": "temperature"},
    "humidity_pct": {"low": 30.0, "high": 60.0, "unit": "%", "label": "relative humidity"},
    "co2_ppm": {"low": None, "high": 1000.0, "unit": "ppm", "label": "CO₂"},
}


def zone_comfort(zones: list[dict]) -> dict:
    """[READ] Occupied-zone comfort + IAQ vs ASHRAE 55 / 62.1.

    ``zones`` are ``{zone, temp_c?, humidity_pct?, co2_ppm?}``. Each provided
    parameter is graded against its range — temperature 20–26 °C, relative
    humidity 30–60 %, CO₂ ≤ 1000 ppm (a ventilation-adequacy proxy) — and each
    zone takes the worst of its parameters (``breach`` when any is out of range),
    worst-first, citing every number. Pure, read-only, advisory.
    """
    graded = [_grade_zone(z) for z in (zones or []) if isinstance(z, dict)]
    summary: dict[str, int] = {}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    graded.sort(key=lambda g: (g["status"] != "breach", g["zone"]))
    breaches = [g for g in graded if g["status"] == "breach"]
    return {
        "zones_evaluated": len(graded),
        "standard": "ASHRAE 55 / 62.1: temp 20–26 °C, RH 30–60 %, CO₂ ≤ 1000 ppm",
        "summary": summary,
        "breach_count": len(breaches),
        "breaches": breaches[:MAX_ROWS],
        "worst": breaches[0] if breaches else None,
    }


def _grade_zone(zone: dict) -> dict:
    name = str(zone.get("zone") or zone.get("name") or "?")
    flags: list[dict] = []
    for key, band in _COMFORT_PARAMS.items():
        value = zone.get(key)
        if not isinstance(value, (int, float)):
            continue
        if band["low"] is not None and value < band["low"]:
            flags.append(_c_flag(band, value, "low", band["low"]))
        elif band["high"] is not None and value > band["high"]:
            flags.append(_c_flag(band, value, "high", band["high"]))
    status = "breach" if flags else ("comfortable" if _has_zone_reading(zone) else "no_data")
    return {"zone": name, "status": status, "flags": flags}


def _c_flag(band: dict, value: float, side: str, bound: float) -> dict:
    return {"parameter": band["label"], "value": value, "unit": band["unit"],
            "detail": f"{band['label']} {value}{band['unit']} is {side} of the "
                      f"{bound}{band['unit']} limit"}


def _has_zone_reading(zone: dict) -> bool:
    return any(isinstance(zone.get(k), (int, float)) for k in _COMFORT_PARAMS)


__all__ = ["economizer_check", "zone_comfort", "MAX_ROWS"]
