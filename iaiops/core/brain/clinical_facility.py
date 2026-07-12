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


__all__ = [
    "isolation_room_check",
    "DEFAULT_MIN_MAGNITUDE_PA",
    "DEFAULT_LOW_MARGIN_PA",
    "MAX_ROWS",
]
