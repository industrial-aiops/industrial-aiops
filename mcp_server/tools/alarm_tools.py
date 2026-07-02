"""ISA-18.2 alarm-flood deepening MCP tools (READ-ONLY).

Live event acquisition reuses the SAME path as the RCA copilot /
``alarm_bad_actors`` pipeline — ``rca_collect.collect_active_alarms`` (a
best-effort OPC-UA active-condition scan; other protocols contribute no alarms).
The scan is polled over ``duration_s`` and appear/disappear transitions become
timestamped ACTIVE/CLEARED events. Analysis itself is pure
(``iaiops.core.brain.alarm_flood``); injected ``events`` skip live collection.
"""

from __future__ import annotations

import csv
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from iaiops.core.brain import alarm_flood as flood
from iaiops.core.brain.rca_collect import collect_active_alarms
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors

MAX_DURATION_S = 300
MIN_POLL_INTERVAL_S = 1.0
MAX_INLINE_ROWS = 50


def _collect_transition_events(
    target: Any, duration_s: int, poll_interval_s: float = 5.0
) -> list[dict]:
    """Poll the active-condition scan over ``duration_s`` → transition events.

    Each poll snapshot is diffed against the previous one: a newly seen source
    becomes an ACTIVE event, a vanished one a CLEARED event, both stamped with
    the poll time (the scan itself yields no per-event time). Bounded: duration
    is capped and the poll interval floored, so this is never an open loop.
    """
    duration = max(1, min(int(duration_s), MAX_DURATION_S))
    interval = max(MIN_POLL_INTERVAL_S, float(poll_interval_s))
    events: list[dict] = []
    previous: set[str] = set()
    deadline = time.monotonic() + duration
    first = True
    while first or time.monotonic() < deadline:
        stamp = datetime.now(tz=UTC).isoformat()
        current = {str(a.get("source", "")) for a in collect_active_alarms(target)}
        for src in sorted(current - previous):
            events.append({"source": src, "timestamp": stamp, "state": "ACTIVE"})
        for src in sorted(previous - current):
            events.append({"source": src, "timestamp": stamp, "state": "CLEARED"})
        previous = current
        first = False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    return events


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alarm_flood_analysis(
    endpoint: Optional[str] = None,
    duration_s: int = 60,
    window_s: float = 600.0,
    threshold: int = 10,
    events: Optional[list[dict[str, Any]]] = None,
    stale_after_s: float = 86400.0,
    max_episodes: int = 20,
    max_rows: int = 50,
) -> dict:
    """[READ][risk=low] ISA-18.2 deep alarm-flood analysis: episodes + chattering + stale.

    Deepens alarm_bad_actors: detects flood *episodes* (start/end/count/peak rate/
    top contributors, per ISA-18.2's >=10 alarms per 10 min per operator), alarms
    chattering ACTIVE↔CLEARED, standing/stale alarms, and percent-time-in-flood vs
    the ISA-18.2 targets (~1-2 alarms/10 min steady state, <1% time in flood).
    Pass 'events' for pure analysis, or an endpoint to collect live via the same
    OPC-UA active-condition scan the RCA copilot uses (polled over duration_s;
    other protocols contribute no alarms). Output is bounded; 'truncated' flags
    say when caps bit.

    Args:
        endpoint: Endpoint name from config (used only when events is omitted).
        duration_s: Live collection window in seconds (1..300, default 60).
        window_s: Flood analysis window in seconds (ISA-18.2 default 600).
        threshold: Annunciations per window that start a flood (default 10).
        events: Injected alarm events — {source, timestamp (ISO-8601), state?
            (ACTIVE/RTN/CLEARED)}; skips live collection entirely.
        stale_after_s: Continuously-active age that marks a standing alarm (default 24h).
        max_episodes: Cap on returned flood episodes (default 20).
        max_rows: Cap on chattering / stale / worksheet-preview rows (default 50).

    Returns dict: {event_count, summary:{insufficient_data, percent_time_in_flood,
        avg_alarms_per_10min, peak_alarms_per_10min, isa_18_2_targets, ...},
        flood_episodes:[{start, end, duration_s, count, peak_count_in_window,
        peak_rate_per_10min, top_contributors}], chattering:[{source, cycles,
        cycles_per_hour, ...}], stale_standing:[{source, active_since,
        active_for_s}], worksheet_preview:[...], truncated:{...}, collected?}.

    Example: alarm_flood_analysis(events=[{"source":"FIC101",
        "timestamp":"2026-06-28T10:00:00Z","state":"ACTIVE"}, ...]).
    """
    collected: dict | None = None
    if events is None:
        target = _target(endpoint)
        events = _collect_transition_events(target, duration_s)
        collected = {
            "endpoint": str(getattr(target, "name", ""))[:64],
            "protocol": str(getattr(target, "protocol", ""))[:16],
            "duration_s": max(1, min(int(duration_s), MAX_DURATION_S)),
            "events_collected": len(events),
        }
    report = flood.alarm_flood_report(
        events, window_s, threshold,
        stale_after_s=stale_after_s, max_episodes=max_episodes, max_rows=max_rows,
    )
    if collected is not None:
        report["collected"] = collected
    return report


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alarm_rationalization_worksheet(
    endpoint: Optional[str] = None,
    duration_s: int = 60,
    events: Optional[list[dict[str, Any]]] = None,
    window_s: float = 600.0,
    threshold: int = 10,
    out_path: Optional[str] = None,
) -> dict:
    """[READ][risk=low] ISA-18.2 alarm-rationalization worksheet (CSV or inline rows).

    One row per alarm source, count-descending: count, % of total annunciations,
    chattering?, flood contributor?, and a recommendation stub — the starting
    document for an ISA-18.2 rationalization review. Pass 'events' for pure
    analysis, or an endpoint to collect live via the same OPC-UA active-condition
    scan the RCA copilot uses. With out_path the full worksheet is written as CSV
    and the path returned; otherwise bounded inline rows (truncation noted).

    Args:
        endpoint: Endpoint name from config (used only when events is omitted).
        duration_s: Live collection window in seconds (1..300, default 60).
        events: Injected alarm events — {source, timestamp (ISO-8601), state?}.
        window_s: Flood analysis window in seconds (ISA-18.2 default 600).
        threshold: Annunciations per window that start a flood (default 10).
        out_path: Optional CSV destination; parent directory must exist.

    Returns dict: {row_count, columns:[alarm_id, count, pct_of_total, chattering,
        in_flood, recommendation], csv_path? , rows?:[...], truncated (bool)}.

    Example: alarm_rationalization_worksheet(events=[...], out_path="worksheet.csv").
    """
    if events is None:
        events = _collect_transition_events(_target(endpoint), duration_s)
    rows = flood.rationalization_worksheet(events, window_s, threshold)
    dicts = flood.worksheet_rows_as_dicts(rows)
    result: dict = {"row_count": len(rows), "columns": list(flood.WORKSHEET_COLUMNS)}
    if out_path:
        path = Path(out_path).expanduser()
        if not path.parent.is_dir():
            raise ValueError(f"Parent directory does not exist: {path.parent}")
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(flood.WORKSHEET_COLUMNS))
            writer.writeheader()
            writer.writerows(dicts)
        result.update({"csv_path": str(path), "truncated": False})
        return result
    result.update({
        "rows": dicts[:MAX_INLINE_ROWS],
        "truncated": len(dicts) > MAX_INLINE_ROWS,
    })
    return result
