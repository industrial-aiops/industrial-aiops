"""Cleanroom checks for GMP manufacturing — pressure cascade and particle counts.

The clinical edition already grades one room's differential against a minimum
(:func:`~iaiops.core.brain.clinical_facility.isolation_room_check`). A GMP
cleanroom suite needs the other question: not "is this room negative enough" but
**"does the cascade hold from A down to D"** — every door between two differently
classified areas has to push from the cleaner side to the dirtier one, and the
chain is only as good as its weakest door. That is what an EU GMP Annex 1
inspection walks, and the failure is silent (a door propped open, a supply fan
drifting) until an environmental-monitoring excursion turns up days later.

**Adjacency is declared, never inferred.** A room list carries no topology, and
guessing which rooms share a door would invent the very relationship the check is
about — the same rule the line-relations layer follows (D25). Without ``doors``
the cascade is reported as not evaluated, with the reason, and the per-room
readings are still graded. Reporting a gap beats filling it in.

**No compendial limits are shipped for particle counts.** The grade/state/size
table belongs to the customer's qualified specification and its compendial
revision; embedding a transcription of it would mean a number nobody in this
repository can verify deciding whether a batch environment passed, and the error
that hurts is the flattering one — a limit set too loose reads as "in
specification". So ``limits`` is required, missing entries are named rather than
skipped, and every verdict cites the number it was compared against.

Advisory and read-only. The site's own qualified EMS and its alarm limits remain
the source of truth; this reads what you pass in.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, s

MAX_ROWS = 200

#: Cleanliness ordering, cleanest first. Annex 1 grades plus the unclassified
#: surround, so a D→CNC door is checkable too.
GRADE_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "CNC")

#: EU GMP Annex 1 guidance for the differential between adjacent rooms of
#: different grade (10–15 Pa). A minimum, and overridable: a site's qualified
#: value is the one that counts.
DEFAULT_MIN_CASCADE_PA = 10.0

_DOOR_SEVERITY = {"reversed": 0, "insufficient": 1, "unknown": 2, "correct": 3}
_ROOM_SEVERITY = {"unknown_grade": 0, "no_reading": 1, "ok": 2}


def _grade_of(value: Any) -> str:
    text = s(value, 8).strip().upper()
    return text if text in GRADE_ORDER else ""


def _rooms(rows: Any) -> dict[str, dict]:
    """Index the room readings by name, keeping what could not be read."""
    out: dict[str, dict] = {}
    for raw in list(rows or ())[:MAX_ROWS]:
        if not isinstance(raw, dict):
            continue
        name = s(raw.get("room", ""), 96)
        if not name:
            continue
        out[name] = {
            "room": name,
            "grade": _grade_of(raw.get("grade")),
            "declared_grade": s(raw.get("grade", ""), 8),
            "pressure_pa": num(raw.get("pressure_pa")),
        }
    return out


def _room_status(room: dict) -> dict:
    if not room["grade"]:
        return {
            **room,
            "status": "unknown_grade",
            "detail": (
                f"grade {room['declared_grade']!r} is not one of "
                f"{'/'.join(GRADE_ORDER)} — not graded rather than guessed"
            ),
        }
    if room["pressure_pa"] is None:
        return {**room, "status": "no_reading", "detail": "no numeric pressure_pa supplied"}
    return {
        **room,
        "status": "ok",
        "detail": f"{room['pressure_pa']} Pa relative to the common reference",
    }


def _door_row(cleaner: str, dirtier: str, rooms: dict[str, dict], min_cascade_pa: float) -> dict:
    a, b = rooms.get(cleaner), rooms.get(dirtier)
    base = {
        "from": cleaner,
        "to": dirtier,
        "from_grade": (a or {}).get("grade", ""),
        "to_grade": (b or {}).get("grade", ""),
        "differential_pa": None,
        "required_pa": min_cascade_pa,
    }
    missing = [n for n, r in ((cleaner, a), (dirtier, b)) if r is None or r["pressure_pa"] is None]
    if missing:
        return {
            **base,
            "status": "unknown",
            "detail": f"no reading for {', '.join(missing)} — the door was not evaluated",
        }
    diff = round(a["pressure_pa"] - b["pressure_pa"], 3)
    row = {**base, "differential_pa": diff}
    if diff < 0:
        return {
            **row,
            "status": "reversed",
            "detail": (
                f"REVERSED: {cleaner} is {abs(diff)} Pa BELOW {dirtier} — air moves from the "
                "dirtier side to the cleaner one"
            ),
        }
    if diff < min_cascade_pa:
        return {
            **row,
            "status": "insufficient",
            "detail": f"{diff} Pa < {min_cascade_pa} Pa required across this door",
        }
    return {**row, "status": "correct", "detail": f"{diff} Pa ≥ {min_cascade_pa} Pa"}


def _doors(raw_doors: Any, rooms: dict[str, dict], min_cascade_pa: float) -> list[dict]:
    rows: list[dict] = []
    for raw in list(raw_doors or ())[:MAX_ROWS]:
        if not isinstance(raw, dict):
            continue
        cleaner = s(raw.get("from", ""), 96)
        dirtier = s(raw.get("to", ""), 96)
        if cleaner and dirtier:
            rows.append(_door_row(cleaner, dirtier, rooms, min_cascade_pa))
    rows.sort(key=lambda r: (_DOOR_SEVERITY.get(r["status"], 9), r["from"], r["to"]))
    return rows


def _tally(rows: list[dict], keys: tuple[str, ...]) -> dict[str, int]:
    counts = dict.fromkeys(keys, 0)
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def cleanroom_pressure_cascade(
    rooms: list[dict],
    doors: list[dict] | None = None,
    min_cascade_pa: float = DEFAULT_MIN_CASCADE_PA,
) -> dict:
    """[READ] Grade a cleanroom pressure cascade door by door (EU GMP Annex 1).

    ``rooms`` are ``{room, grade ('A'|'B'|'C'|'D'|'CNC'), pressure_pa}`` where
    ``pressure_pa`` is each room's pressure against ONE common reference (typically
    the unclassified corridor or outside) — differentials are then computed here
    rather than read from doors that may disagree with each other.

    ``doors`` are ``{from, to}`` with ``from`` the side that must be cleaner. They
    are **declared**: a room list carries no topology and guessing adjacency would
    invent the relationship being checked. Omit them and the cascade is reported
    as not evaluated, naming what would make it evaluable; the rooms are still
    graded.

    Each door is ``correct`` / ``insufficient`` / ``reversed`` / ``unknown``,
    worst-first, citing the differential and the requirement.
    """
    indexed = _rooms(rooms)
    room_rows = sorted(
        (_room_status(r) for r in indexed.values()),
        key=lambda r: (_ROOM_SEVERITY.get(r["status"], 9), r["room"]),
    )
    door_rows = _doors(doors, indexed, min_cascade_pa)
    cascade = {
        "evaluated": bool(door_rows),
        "doors_evaluated": len(door_rows),
        "summary": _tally(door_rows, tuple(_DOOR_SEVERITY)),
        "doors": door_rows,
    }
    if not door_rows:
        cascade["why_not"] = (
            "No doors were declared, so no cascade was evaluated. Pass "
            "doors=[{from: <cleaner room>, to: <dirtier room>}] — adjacency is "
            "declared rather than inferred, because a room list carries no "
            "topology and a guessed door would invent the relationship this "
            "check exists to test."
        )
    failures = [d for d in door_rows if d["status"] in ("reversed", "insufficient")]
    return {
        "standard": "EU GMP Annex 1 — pressure cascade between adjacent classified areas",
        "min_cascade_pa": min_cascade_pa,
        "grade_order": list(GRADE_ORDER),
        "rooms_evaluated": len(room_rows),
        "rooms": room_rows,
        "cascade": cascade,
        "failure_count": len(failures),
        "worst": door_rows[0] if door_rows else None,
        "advisory": (
            "Advisory analysis of readings you supplied. The site's qualified EMS "
            "and its alarm limits remain the source of truth; nothing was read "
            "from or written to a device here."
        ),
    }


# ── particle counts ──────────────────────────────────────────────────────────

_PARTICLE_SEVERITY = {"exceeded": 0, "no_limit": 1, "no_reading": 2, "within_limit": 3}


def _limit_for(limits: Any, grade: str, state: str, size: str) -> float | None:
    if not isinstance(limits, dict):
        return None
    by_state = limits.get(grade)
    if not isinstance(by_state, dict):
        return None
    by_size = by_state.get(state)
    if not isinstance(by_size, dict):
        return None
    return num(by_size.get(size))


def _particle_rows(sample: dict, limits: Any) -> list[dict]:
    room = s(sample.get("room", ""), 96)
    grade = _grade_of(sample.get("grade"))
    state = s(sample.get("state", ""), 24).strip().lower()
    counts = sample.get("particles_per_m3")
    rows: list[dict] = []
    if not isinstance(counts, dict) or not counts:
        return [
            {
                "room": room,
                "grade": grade,
                "state": state,
                "size_um": "",
                "count_per_m3": None,
                "limit_per_m3": None,
                "status": "no_reading",
                "detail": "no particles_per_m3 counts supplied",
            }
        ]
    for size, raw in sorted(counts.items(), key=lambda kv: str(kv[0])):
        size_label = s(size, 16)
        count = num(raw)
        limit = _limit_for(limits, grade, state, str(size)) if grade and state else None
        row = {
            "room": room,
            "grade": grade,
            "state": state,
            "size_um": size_label,
            "count_per_m3": count,
            "limit_per_m3": limit,
        }
        if count is None:
            rows.append({**row, "status": "no_reading", "detail": "count is not numeric"})
        elif limit is None:
            rows.append(
                {
                    **row,
                    "status": "no_limit",
                    "detail": (
                        f"no limit supplied for grade {grade or '?'} / {state or '?'} / "
                        f"{size_label} µm — not graded rather than assumed"
                    ),
                }
            )
        elif count > limit:
            rows.append(
                {
                    **row,
                    "status": "exceeded",
                    "detail": f"{count} > {limit} per m³ at ≥{size_label} µm",
                }
            )
        else:
            rows.append(
                {
                    **row,
                    "status": "within_limit",
                    "detail": f"{count} ≤ {limit} per m³ at ≥{size_label} µm",
                }
            )
    return rows


def cleanroom_particle_check(samples: list[dict], limits: dict) -> dict:
    """[READ] Grade airborne particle counts against the limits YOU supply.

    ``samples`` are ``{room, grade, state ('at_rest'|'in_operation'),
    particles_per_m3: {"0.5": n, "5.0": n}}``.

    ``limits`` is ``{grade: {state: {size: max_per_m3}}}`` and is **required**.
    No compendial table is shipped: the grade/state/size limits belong to the
    site's qualified specification at its compendial revision, and a
    transcription nobody here can verify would decide whether a batch environment
    passed — with the flattering error (a limit set too loose) reading as "in
    specification". A missing entry is reported as ``no_limit`` and named, never
    skipped and never assumed.

    Each (room, size) is ``within_limit`` / ``exceeded`` / ``no_limit`` /
    ``no_reading``, worst-first, citing both numbers.
    """
    rows: list[dict] = []
    for sample in list(samples or ())[:MAX_ROWS]:
        if isinstance(sample, dict):
            rows.extend(_particle_rows(sample, limits))
    rows.sort(key=lambda r: (_PARTICLE_SEVERITY.get(r["status"], 9), r["room"], r["size_um"]))
    ungraded = [r for r in rows if r["status"] in ("no_limit", "no_reading")]
    return {
        "standard": "airborne particulate cleanliness — limits supplied by the caller",
        "readings_evaluated": len(rows),
        "summary": _tally(rows, tuple(_PARTICLE_SEVERITY)),
        "exceeded_count": sum(1 for r in rows if r["status"] == "exceeded"),
        "ungraded_count": len(ungraded),
        "readings": rows,
        "worst": rows[0] if rows else None,
        "advisory": (
            "Advisory. Limits are yours, not ours — this compares what you passed "
            "in against what you declared and cites both. Ungraded readings are "
            "listed rather than counted as passing."
        ),
    }


__all__ = [
    "DEFAULT_MIN_CASCADE_PA",
    "GRADE_ORDER",
    "cleanroom_particle_check",
    "cleanroom_pressure_cascade",
]
