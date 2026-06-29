"""OEE / downtime auto-capture — cross-protocol, read-only analytics.

Protocol-agnostic analysis over **provided / collected** series, so it is fully
testable without a live plant: the caller injects the inputs (planned time, run
state series, counts) and these functions compute the result.

  * ``oee_compute`` — Availability × Performance × Quality from the classic OEE
    inputs (planned time, run time, ideal cycle, total/good counts).
  * ``downtime_events`` — detect running→stopped transitions in a state/tag
    series, produce stoppage events with durations, and categorize them
    (changeover / material / mechanical / quality / break / unknown).
  * ``oee_multidim`` — aggregate OEE across dimensions (machine × part × shift)
    from labelled records, returning the matrix + worst performers.

All outputs are structured JSON designed for an agent to visualize. Each ratio is
reported raw and clamped to [0,1] (a >100% performance, common with a slightly
optimistic ideal cycle, is flagged rather than silently hidden).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from iaiops.core.brain._shared import num, s

MAX_RECORDS = 5000
MAX_SERIES = 10000

# Default state vocabulary: anything in RUNNING_STATES counts as productive run
# time; everything else is a stoppage. Vendor-neutral, case-insensitive.
RUNNING_STATES = frozenset(
    {"RUNNING", "ACTIVE", "AUTO", "PRODUCING", "RUN", "ON", "1", "TRUE", "AVAILABLE"}
)

# Default downtime categories by keyword found in a state/reason label.
DEFAULT_CATEGORY_KEYWORDS = {
    "changeover": ("changeover", "setup", "product change", "tool change"),
    "material": ("material", "starved", "blocked", "no part", "feed"),
    "mechanical": ("fault", "jam", "mechanical", "breakdown", "estop", "e-stop", "trip"),
    "quality": ("quality", "reject", "scrap", "defect"),
    "break": ("break", "lunch", "meeting", "planned", "maintenance"),
}


def _ratio(numerator: float, denominator: float) -> dict:
    """Compute a ratio reporting both the raw value and a [0,1]-clamped value."""
    if denominator <= 0:
        return {"raw": 0.0, "value": 0.0, "capped": False}
    raw = numerator / denominator
    value = max(0.0, min(raw, 1.0))
    return {"raw": round(raw, 6), "value": round(value, 6), "capped": raw > 1.0}


def oee_compute(
    planned_time_s: float,
    run_time_s: float,
    ideal_cycle_time_s: float,
    total_count: float,
    good_count: float,
) -> dict:
    """[READ] OEE = Availability × Performance × Quality from production inputs.

    Availability = run_time / planned_time; Performance = (ideal_cycle ×
    total_count) / run_time; Quality = good_count / total_count. Each factor is
    reported raw + clamped to [0,1]; OEE uses the clamped factors.
    """
    planned = max(0.0, num(planned_time_s) or 0.0)
    run = max(0.0, num(run_time_s) or 0.0)
    ideal = max(0.0, num(ideal_cycle_time_s) or 0.0)
    total = max(0.0, num(total_count) or 0.0)
    good = max(0.0, num(good_count) or 0.0)

    availability = _ratio(run, planned)
    performance = _ratio(ideal * total, run)
    quality = _ratio(good, total)
    oee = round(availability["value"] * performance["value"] * quality["value"], 6)

    losses = {
        "availability_loss_s": round(max(0.0, planned - run), 3),
        "quality_loss_count": round(max(0.0, total - good), 3),
    }
    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
        "oee_pct": round(oee * 100.0, 2),
        "inputs": {
            "planned_time_s": planned, "run_time_s": run,
            "ideal_cycle_time_s": ideal, "total_count": total, "good_count": good,
        },
        "losses": losses,
        "note": "Factors reported raw + clamped to [0,1]; OEE uses clamped factors. "
        "A 'capped' performance >1.0 usually means the ideal cycle time is optimistic.",
    }


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerant of a trailing Z), else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_running(state: Any) -> bool:
    """True if a state/value counts as productive run time."""
    if isinstance(state, bool):
        return state
    if isinstance(state, (int, float)):
        return state != 0
    return str(state).strip().upper() in RUNNING_STATES


def _categorize(label: str, category_map: dict[str, str] | None) -> str:
    """Map a stoppage state/reason label to a downtime category."""
    text = (label or "").strip().lower()
    if category_map:
        # Exact (case-insensitive) state→category override wins.
        for key, cat in category_map.items():
            if key.strip().lower() == text:
                return s(str(cat), 32)
    for cat, keywords in DEFAULT_CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return "unknown"


def downtime_events(
    series: list[dict],
    category_map: dict[str, str] | None = None,
    min_duration_s: float = 0.0,
) -> dict:
    """[READ] Detect running→stopped transitions and categorize the stoppages.

    Each sample: ``{timestamp, state}`` (or ``value``); ``state`` may be a string
    (RUNNING/IDLE/FAULT…), a bool, or a number. The series is sorted by timestamp;
    every span where the machine is NOT running becomes a stoppage event with a
    duration and a category (changeover/material/mechanical/quality/break/unknown).
    """
    rows: list[dict] = []
    for item in (series or [])[:MAX_SERIES]:
        if not isinstance(item, dict):
            continue
        ts = _parse_ts(item.get("timestamp") or item.get("time"))
        if ts is None:
            continue
        state = item.get("state", item.get("value"))
        rows.append({"ts": ts, "state": state})
    rows.sort(key=lambda r: r["ts"])
    if len(rows) < 2:
        return {"error": "Need >=2 timestamped samples to detect transitions.",
                "samples": len(rows)}

    events: list[dict] = []
    open_event: dict | None = None
    for i, row in enumerate(rows):
        running = _is_running(row["state"])
        if not running and open_event is None:
            open_event = {"start_ts": row["ts"], "state": row["state"]}
        elif running and open_event is not None:
            _close_event(events, open_event, row["ts"], category_map)
            open_event = None
    if open_event is not None:
        _close_event(events, open_event, rows[-1]["ts"], category_map)

    events = [e for e in events if e["duration_s"] >= max(0.0, min_duration_s)]
    by_category: dict[str, dict] = {}
    for e in events:
        agg = by_category.setdefault(e["category"], {"count": 0, "downtime_s": 0.0})
        agg["count"] += 1
        agg["downtime_s"] = round(agg["downtime_s"] + e["duration_s"], 3)
    total_downtime = round(sum(e["duration_s"] for e in events), 3)
    return {
        "samples": len(rows),
        "event_count": len(events),
        "total_downtime_s": total_downtime,
        "by_category": by_category,
        "events": events[:MAX_RECORDS],
    }


def _close_event(
    events: list[dict], open_event: dict, end_ts: datetime, category_map: dict | None
) -> None:
    """Finalize a stoppage span into an event record."""
    duration = max(0.0, (end_ts - open_event["start_ts"]).total_seconds())
    label = str(open_event["state"]) if open_event["state"] is not None else ""
    events.append(
        {
            "start": s(str(open_event["start_ts"]), 40),
            "end": s(str(end_ts), 40),
            "duration_s": round(duration, 3),
            "state": s(label, 48),
            "category": _categorize(label, category_map),
        }
    )


def oee_multidim(
    records: list[dict],
    dimensions: list[str] | None = None,
) -> dict:
    """[READ] Aggregate OEE across dimensions (e.g. machine × part × shift).

    Each record carries dimension labels plus the OEE inputs (``planned_time_s``,
    ``run_time_s``, ``ideal_cycle_time_s``, ``total_count``, ``good_count``).
    Records sharing the same dimension-tuple are summed, then OEE is computed for
    the group. Returns the matrix + the worst performers (lowest OEE).
    """
    dims = [str(d) for d in (dimensions or ["machine", "part", "shift"])][:6]
    rows = [r for r in (records or [])[:MAX_RECORDS] if isinstance(r, dict)]
    if not rows:
        return {"error": "No records. Pass [{<dimensions>, planned_time_s, ...}]."}

    groups: dict[tuple, dict] = {}
    for r in rows:
        key = tuple(s(str(r.get(d, "")), 48) for d in dims)
        agg = groups.setdefault(
            key,
            {"planned_time_s": 0.0, "run_time_s": 0.0, "ideal_cycle_time_s": 0.0,
             "total_count": 0.0, "good_count": 0.0, "_ideal_n": 0},
        )
        agg["planned_time_s"] += num(r.get("planned_time_s")) or 0.0
        agg["run_time_s"] += num(r.get("run_time_s")) or 0.0
        agg["total_count"] += num(r.get("total_count")) or 0.0
        agg["good_count"] += num(r.get("good_count")) or 0.0
        ideal = num(r.get("ideal_cycle_time_s"))
        if ideal is not None:
            agg["ideal_cycle_time_s"] += ideal
            agg["_ideal_n"] += 1

    matrix: list[dict] = []
    for key, agg in groups.items():
        ideal_avg = agg["ideal_cycle_time_s"] / agg["_ideal_n"] if agg["_ideal_n"] else 0.0
        oee = oee_compute(
            agg["planned_time_s"], agg["run_time_s"], ideal_avg,
            agg["total_count"], agg["good_count"],
        )
        matrix.append(
            {
                "dimensions": dict(zip(dims, key, strict=False)),
                "oee": oee["oee"],
                "oee_pct": oee["oee_pct"],
                "availability": oee["availability"]["value"],
                "performance": oee["performance"]["value"],
                "quality": oee["quality"]["value"],
            }
        )
    matrix.sort(key=lambda m: m["oee"])
    overall = round(sum(m["oee"] for m in matrix) / len(matrix), 6) if matrix else 0.0
    return {
        "dimensions": dims,
        "group_count": len(matrix),
        "mean_oee": overall,
        "worst_performers": matrix[: min(5, len(matrix))],
        "matrix": matrix,
    }


__all__ = ["oee_compute", "downtime_events", "oee_multidim"]
