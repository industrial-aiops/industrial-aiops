"""Clinical-facility checks — isolation-room pressure compliance (pure analysis).

The healthcare slice of the building edition. Generic BMS watches comfort
(temperature, CO2); a hospital facility team watches things that are *patient
safety*, the sharpest being **room pressurization**:

  * **Airborne Infection Isolation (AII)** rooms must stay **negative** to the
    corridor so infectious air cannot escape (TB, measles, COVID).
  * **Protective Environment (PE)** rooms (transplant / immunocompromised) must
    stay **positive** so unfiltered air cannot get in.

ASHRAE 170 and CDC guidance set a minimum differential of ~2.5 Pa (0.01" w.c.).
A room at the wrong polarity, or too weak, is a reportable safety event — and
the classic failure is silent (a door left open, a fan belt slipping).

``isolation_room_check`` is a pure function over differential-pressure readings
(from BACnet AI points / a historian): it classifies each room against its
required mode and the minimum, worst-first, citing the number behind every
flag. Read-only and advisory.
"""

from __future__ import annotations

from typing import Any

MAX_ROWS = 100

# ASHRAE 170 / CDC minimum room-to-corridor differential (Pa) for AII / PE rooms.
DEFAULT_MIN_MAGNITUDE_PA = 2.5
# Correct polarity but within this magnitude of the minimum → flagged low_margin.
DEFAULT_LOW_MARGIN_PA = 5.0

# Required differential sign per mode (room-minus-reference): negative room is
# lower than the corridor. 'neutral' rooms are reported for information only.
_REQUIRED_SIGN = {"negative": -1, "positive": 1, "neutral": 0}

# Worst-first ordering for the breach list.
_SEVERITY = {"reversed": 0, "breach": 1, "low_margin": 2, "compliant": 3, "info": 4}


def isolation_room_check(
    rooms: list[dict],
    min_magnitude_pa: float = DEFAULT_MIN_MAGNITUDE_PA,
    low_margin_pa: float = DEFAULT_LOW_MARGIN_PA,
) -> dict:
    """[READ] Classify isolation-room pressurization against ASHRAE 170 / CDC minimums.

    ``rooms`` are ``{room, mode ('negative'|'positive'|'neutral'), differential_pa}``
    where ``differential_pa`` is the room-minus-reference pressure (a negative
    number means the room is below the corridor). Each room is graded
    ``compliant | low_margin | breach | reversed`` (or ``info`` for neutral):
    *reversed* = wrong polarity (the dangerous, reportable case); *breach* =
    right polarity but below the minimum; *low_margin* = correct but within
    ``low_margin_pa`` of the minimum. Worst-first; every flag cites its number.
    """
    graded = [
        _grade(r, min_magnitude_pa, low_margin_pa)
        for r in (rooms or [])
        if isinstance(r, dict)
    ]
    summary = {k: 0 for k in ("compliant", "low_margin", "breach", "reversed", "info")}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    graded.sort(key=lambda g: (_SEVERITY.get(g["status"], 9), g["room"]))
    breaches = [g for g in graded if g["status"] in ("reversed", "breach", "low_margin")]
    return {
        "rooms_evaluated": len(graded),
        "standard": (
            "ASHRAE 170 / CDC: AII negative & PE positive, minimum "
            f"{min_magnitude_pa} Pa (~0.01 in. w.c.) room-to-corridor differential"
        ),
        "min_magnitude_pa": min_magnitude_pa,
        "low_margin_pa": low_margin_pa,
        "summary": summary,
        "breach_count": len(breaches),
        "breaches": breaches[:MAX_ROWS],
        "worst": breaches[0] if breaches else None,
    }


def _grade(room: dict, min_magnitude_pa: float, low_margin_pa: float) -> dict:
    """Grade one room's differential against its required mode + the minimum."""
    name = str(room.get("room") or room.get("name") or "?")
    mode = str(room.get("mode") or "neutral").lower()
    diff = room.get("differential_pa", room.get("differential"))
    req = _REQUIRED_SIGN.get(mode, 0)

    if not isinstance(diff, (int, float)):
        return _row(name, mode, None, "unknown", "no numeric differential_pa reading")

    magnitude = abs(diff)
    sign = -1 if diff < 0 else (1 if diff > 0 else 0)

    if req == 0:  # neutral room — informational, no polarity requirement
        status, detail = "info", f"neutral room; differential {diff} Pa (not graded)"
    elif sign != 0 and sign != req:
        want = "negative" if req < 0 else "positive"
        status = "reversed"
        detail = f"REVERSED: {diff} Pa is {_polarity(sign)} but must be {want} — safety event"
    elif magnitude < min_magnitude_pa:
        status = "breach"
        detail = f"insufficient: |{diff}| Pa < {min_magnitude_pa} Pa minimum"
    elif magnitude < low_margin_pa:
        status = "low_margin"
        detail = f"low margin: |{diff}| Pa is within {low_margin_pa} Pa of the minimum"
    else:
        status = "compliant"
        detail = f"ok: {diff} Pa maintains the required {mode} pressure"
    return _row(name, mode, diff, status, detail)


def _polarity(sign: int) -> str:
    return "positive" if sign > 0 else "negative" if sign < 0 else "neutral"


def _row(room: str, mode: str, diff: Any, status: str, detail: str) -> dict:
    return {"room": room, "mode": mode, "differential_pa": diff,
            "status": status, "detail": detail}


# ── Medical gas / vacuum source pressure (NFPA 99 / HTM 02-01) ────────────────
# Default normal bands per gas, in kPa (gauge). Positive-pressure medical gases
# run ~345–380 kPa (50–55 psi) at the source; medical vacuum is a *negative*
# gauge pressure that must be at least as deep as the threshold (i.e. ≤ it).
# These are guidance defaults — a facility overrides per its NFPA 99 / HTM
# commissioning values. ``kind`` selects the grading rule.
_POSITIVE_BAND = {"low": 345.0, "high": 380.0, "crit_low": 310.0, "crit_high": 415.0}
_GAS_BANDS: dict[str, dict] = {
    "oxygen": {"kind": "positive", **_POSITIVE_BAND},
    "medical_air": {"kind": "positive", **_POSITIVE_BAND},
    "nitrous_oxide": {"kind": "positive", **_POSITIVE_BAND},
    "nitrogen": {"kind": "positive", **_POSITIVE_BAND},
    "carbon_dioxide": {"kind": "positive", **_POSITIVE_BAND},
    "vacuum": {"kind": "vacuum", "adequate_at_or_below": -40.0, "crit_above": -27.0},
    "wagd": {"kind": "vacuum", "adequate_at_or_below": -40.0, "crit_above": -27.0},
}

# Worst-first ordering for medical-gas findings.
_GAS_SEVERITY = {"critical": 0, "low_pressure": 1, "high_pressure": 1,
                 "insufficient_vacuum": 1, "unknown_gas": 2, "unknown": 3, "normal": 4}


def medical_gas_check(sources: list[dict]) -> dict:
    """[READ] Grade medical-gas / vacuum source pressures against NFPA 99 bands.

    ``sources`` are ``{system, gas, pressure_kpa}`` (gauge). Positive-pressure
    gases (oxygen / medical air / N2O / nitrogen / CO2) must sit inside their
    normal band (~345–380 kPa); medical vacuum / WAGD must be at least as deep as
    the vacuum threshold. Each source is graded ``normal | low_pressure |
    high_pressure | insufficient_vacuum | critical`` (or ``unknown_gas`` when the
    gas has no band), worst-first, citing the number behind every flag. Pure,
    read-only, advisory — the source of truth is the station's NFPA 99 alarm panel.
    """
    graded = [_grade_gas(s) for s in (sources or []) if isinstance(s, dict)]
    summary: dict[str, int] = {}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    graded.sort(key=lambda g: (_GAS_SEVERITY.get(g["status"], 9), g["system"]))
    alarms = [g for g in graded if g["status"] not in ("normal", "unknown_gas", "unknown")]
    return {
        "sources_evaluated": len(graded),
        "standard": "NFPA 99 / HTM 02-01 medical gas & vacuum source pressures "
                    "(guidance defaults; kPa gauge)",
        "summary": summary,
        "alarm_count": len(alarms),
        "alarms": alarms[:MAX_ROWS],
        "worst": alarms[0] if alarms else None,
    }


def _grade_gas(source: dict) -> dict:
    """Grade one medical-gas/vacuum source against its NFPA 99 band."""
    system = str(source.get("system") or source.get("name") or "?")
    gas = str(source.get("gas") or "").lower()
    kpa = source.get("pressure_kpa", source.get("pressure"))
    band = _GAS_BANDS.get(gas)
    if band is None:
        return _gas_row(system, gas, kpa, "unknown_gas", f"no NFPA band for gas '{gas}'")
    if not isinstance(kpa, (int, float)):
        return _gas_row(system, gas, kpa, "unknown", "no numeric pressure_kpa reading")
    if band["kind"] == "vacuum":
        return _grade_vacuum(system, gas, float(kpa), band)
    return _grade_positive(system, gas, float(kpa), band)


def _grade_positive(system: str, gas: str, kpa: float, band: dict) -> dict:
    if kpa <= band["crit_low"] or kpa >= band["crit_high"]:
        return _gas_row(system, gas, kpa, "critical",
                        f"critical: {kpa} kPa outside [{band['crit_low']}, {band['crit_high']}]")
    if kpa < band["low"]:
        return _gas_row(system, gas, kpa, "low_pressure", f"low: {kpa} kPa < {band['low']} kPa")
    if kpa > band["high"]:
        return _gas_row(system, gas, kpa, "high_pressure",
                        f"high: {kpa} kPa > {band['high']} kPa")
    return _gas_row(system, gas, kpa, "normal",
                    f"ok: {kpa} kPa within [{band['low']}, {band['high']}]")


def _grade_vacuum(system: str, gas: str, kpa: float, band: dict) -> dict:
    if kpa > band["crit_above"]:
        return _gas_row(system, gas, kpa, "critical",
                        f"critical: {kpa} kPa vacuum far above {band['crit_above']} kPa")
    if kpa > band["adequate_at_or_below"]:
        return _gas_row(system, gas, kpa, "insufficient_vacuum",
                        f"insufficient: {kpa} kPa > {band['adequate_at_or_below']} kPa threshold")
    return _gas_row(system, gas, kpa, "normal",
                    f"ok: {kpa} kPa at or below the {band['adequate_at_or_below']} kPa threshold")


def _gas_row(system: str, gas: str, kpa: Any, status: str, detail: str) -> dict:
    return {"system": system, "gas": gas, "pressure_kpa": kpa,
            "status": status, "detail": detail}


# ── Operating-room ventilation (ASHRAE 170 Table 7.1) ────────────────────────
# Default acceptable ranges for OR / procedure-room environment. A facility
# overrides per its commissioning values. air_changes_per_hour is a minimum.
_OR_PARAMS: dict[str, dict] = {
    "temp_c": {"low": 20.0, "high": 24.0, "unit": "°C", "label": "temperature"},
    "humidity_pct": {"low": 20.0, "high": 60.0, "unit": "%", "label": "relative humidity"},
    "air_changes_per_hour": {"low": 20.0, "high": None, "unit": "ACH",
                             "label": "air changes/hour"},
}


def or_environment_check(rooms: list[dict]) -> dict:
    """[READ] Operating-room ventilation compliance (ASHRAE 170 Table 7.1).

    ``rooms`` are ``{room, temp_c?, humidity_pct?, air_changes_per_hour?}``. Each
    provided parameter is graded against its acceptable range — temperature
    20–24 °C, relative humidity 20–60 %, air changes ≥ 20/hr — and each room takes
    the worst of its parameters (``breach`` when any is out of range). Worst-first,
    citing every number. Pure, read-only, advisory.
    """
    graded = [_grade_or_room(r) for r in (rooms or []) if isinstance(r, dict)]
    summary: dict[str, int] = {}
    for g in graded:
        summary[g["status"]] = summary.get(g["status"], 0) + 1
    graded.sort(key=lambda g: (g["status"] != "breach", g["room"]))
    breaches = [g for g in graded if g["status"] == "breach"]
    return {
        "rooms_evaluated": len(graded),
        "standard": "ASHRAE 170 Table 7.1 OR: temp 20–24 °C, RH 20–60 %, ≥20 ACH",
        "summary": summary,
        "breach_count": len(breaches),
        "breaches": breaches[:MAX_ROWS],
        "worst": breaches[0] if breaches else None,
    }


def _grade_or_room(room: dict) -> dict:
    """Grade one OR's provided environment parameters against ASHRAE 170."""
    name = str(room.get("room") or room.get("name") or "?")
    flags: list[dict] = []
    for key, band in _OR_PARAMS.items():
        value = room.get(key)
        if not isinstance(value, (int, float)):
            continue
        if value < band["low"]:
            flags.append(_or_flag(band, value, "low"))
        elif band["high"] is not None and value > band["high"]:
            flags.append(_or_flag(band, value, "high"))
    status = "breach" if flags else ("compliant" if _has_reading(room) else "no_data")
    return {"room": name, "status": status, "flags": flags}


def _or_flag(band: dict, value: float, side: str) -> dict:
    bound = band["low"] if side == "low" else band["high"]
    return {"parameter": band["label"], "value": value, "unit": band["unit"],
            "detail": f"{band['label']} {value}{band['unit']} is {side} of the "
                      f"{bound}{band['unit']} limit"}


def _has_reading(room: dict) -> bool:
    return any(isinstance(room.get(k), (int, float)) for k in _OR_PARAMS)


__all__ = [
    "isolation_room_check",
    "medical_gas_check",
    "or_environment_check",
    "DEFAULT_MIN_MAGNITUDE_PA",
    "DEFAULT_LOW_MARGIN_PA",
    "MAX_ROWS",
]
