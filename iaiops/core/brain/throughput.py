"""Line throughput bottleneck finder — Theory-of-Constraints over station data.

The warehouse / discrete-line question OEE does not directly answer: *which
station is capping the line, and how do I know?* A line runs no faster than its
slowest station (the constraint), so the bottleneck is the station with the
lowest throughput (equivalently the longest cycle time). Starvation and blocking
corroborate it: the constraint itself is rarely starved or blocked (it is always
working), while stations upstream of it get **blocked** (their output backs up)
and stations downstream get **starved** (they wait for its output).

``line_bottleneck`` is a pure function over per-station throughput / cycle-time
readings (from a WMS/WCS, MES, or PLC counters). It ranks the line, names the
constraint, reports the line rate it sets, flags co-constraints running close
behind, and tags each station starved / blocked — every call citing the number.
Read-only and advisory.
"""

from __future__ import annotations

MAX_ROWS = 100

# A station within this % of the slowest is a co-constraint worth watching.
DEFAULT_NEAR_PCT = 10.0
# starved/blocked fraction (%) above which a station is tagged as such.
_STARVED_BLOCKED_PCT = 20.0


def line_bottleneck(stations: list[dict], near_pct: float = DEFAULT_NEAR_PCT) -> dict:
    """[READ] Find the line's throughput constraint and the evidence around it.

    ``stations`` are ``{station, throughput_per_hr | cycle_time_s, starved_pct?,
    blocked_pct?}`` — give either a throughput or a cycle time (throughput wins
    if both are present; cycle time converts as 3600/cycle_time_s). The station
    with the lowest throughput is the bottleneck; it sets ``lineRatePerHr`` (the
    ceiling for the whole line). Returns the constraint, the ranked line, any
    co-constraints within ``near_pct``, and per-station starved/blocked flags.
    """
    rows = [r for r in (_row(s) for s in (stations or []) if isinstance(s, dict)) if r]
    analyzed = len(rows)
    ignored = len([s for s in (stations or []) if isinstance(s, dict)]) - analyzed
    if not rows:
        return {"stations_analyzed": 0, "ignored": ignored, "bottleneck": None,
                "lineRatePerHr": None, "ranked": [], "nearBottleneck": [], "note": _NOTE}

    rows.sort(key=lambda r: r["throughputPerHr"])
    bottleneck = rows[0]
    line_rate = bottleneck["throughputPerHr"]
    near_cutoff = line_rate * (1.0 + max(0.0, near_pct) / 100.0)

    ranked = [_rank_row(r, line_rate, near_cutoff, bottleneck["station"]) for r in rows]
    near = [r["station"] for r in ranked if r["flag"] == "co_constraint"]
    return {
        "stations_analyzed": analyzed,
        "ignored": ignored,
        "bottleneck": {
            "station": bottleneck["station"],
            "throughputPerHr": bottleneck["throughputPerHr"],
            "cycleTimeS": bottleneck["cycleTimeS"],
            "starvedPct": bottleneck["starvedPct"],
            "blockedPct": bottleneck["blockedPct"],
        },
        "lineRatePerHr": round(line_rate, 3),
        "ranked": ranked[:MAX_ROWS],
        "nearBottleneck": near[:MAX_ROWS],
        "note": _NOTE,
    }


_NOTE = (
    "Advisory Theory-of-Constraints read over injected per-station throughput; the "
    "slowest station is the line's constraint (it sets the line rate). Starvation "
    "points upstream to the constraint, blocking points downstream — corroborate "
    "against the line layout before acting."
)


def _throughput_per_hr(source: dict) -> float | None:
    """Throughput in units/hr from an explicit rate, else from a cycle time."""
    tph = source.get("throughput_per_hr", source.get("throughput"))
    if isinstance(tph, (int, float)) and tph > 0:
        return float(tph)
    cycle = source.get("cycle_time_s", source.get("cycle_time"))
    if isinstance(cycle, (int, float)) and cycle > 0:
        return 3600.0 / float(cycle)
    return None


def _row(source: dict) -> dict | None:
    """Normalize one station; None when it carries no usable throughput signal."""
    tph = _throughput_per_hr(source)
    if tph is None:
        return None
    return {
        "station": str(source.get("station") or source.get("name") or "?"),
        "throughputPerHr": round(tph, 3),
        "cycleTimeS": round(3600.0 / tph, 3) if tph > 0 else None,
        "starvedPct": _pct(source.get("starved_pct")),
        "blockedPct": _pct(source.get("blocked_pct")),
    }


def _pct(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _rank_row(row: dict, line_rate: float, near_cutoff: float, bottleneck_name: str) -> dict:
    """Add vs-bottleneck delta + a role flag to a ranked station row."""
    tph = row["throughputPerHr"]
    vs = round((tph - line_rate) / line_rate * 100.0, 1) if line_rate else None
    if row["station"] == bottleneck_name:
        flag = "bottleneck"
    elif tph <= near_cutoff:
        flag = "co_constraint"
    elif _over(row["starvedPct"]):
        flag = "starved"        # waiting for upstream — points toward the constraint upstream
    elif _over(row["blockedPct"]):
        flag = "blocked"        # output backed up — the constraint is downstream
    else:
        flag = "ok"
    return {**row, "vsBottleneckPct": vs, "flag": flag}


def _over(pct: float | None) -> bool:
    return isinstance(pct, (int, float)) and pct >= _STARVED_BLOCKED_PCT


__all__ = ["line_bottleneck", "MAX_ROWS", "DEFAULT_NEAR_PCT"]
