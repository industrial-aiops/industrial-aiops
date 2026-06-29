"""OEE / downtime analytics MCP tools (READ-ONLY, protocol-agnostic).

All analytics are non-destructive (risk_level='low') and operate over provided /
collected inputs, so they need no live plant. Structured JSON for agent visuals.
"""

from typing import Optional

from iaiops.core.brain import oee as ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def oee_compute(
    planned_time_s: float,
    run_time_s: float,
    ideal_cycle_time_s: float,
    total_count: float,
    good_count: float,
) -> dict:
    """[READ][risk=low] OEE = Availability × Performance × Quality from inputs.

    Args:
        planned_time_s: Planned production time (seconds).
        run_time_s: Actual running time (seconds) — planned minus downtime.
        ideal_cycle_time_s: Ideal/nameplate cycle time per part (seconds).
        total_count: Total parts produced.
        good_count: Good (non-reject) parts produced.

    Returns dict: {availability, performance, quality (each {raw, value, capped}),
        oee, oee_pct, inputs, losses}.

    Example: oee_compute(planned_time_s=28800, run_time_s=25200,
        ideal_cycle_time_s=2.0, total_count=12000, good_count=11800).
    """
    return ops.oee_compute(
        planned_time_s, run_time_s, ideal_cycle_time_s, total_count, good_count
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def downtime_events(
    series: list,
    category_map: Optional[dict] = None,
    min_duration_s: float = 0.0,
) -> dict:
    """[READ][risk=low] Detect running→stopped transitions and categorize stoppages.

    Args:
        series: Timestamped samples — {timestamp (ISO-8601), state} where state is
            a string (RUNNING/IDLE/FAULT…), a bool, or a number.
        category_map: Optional {state_label: category} override (else keyword
            heuristics map to changeover/material/mechanical/quality/break/unknown).
        min_duration_s: Ignore stoppages shorter than this (seconds).

    Returns dict: {samples, event_count, total_downtime_s, by_category:{cat:
        {count, downtime_s}}, events:[{start, end, duration_s, state, category}]}.

    Example: downtime_events(series=[{"timestamp":"2026-06-28T08:00:00Z","state":"RUNNING"},
        {"timestamp":"2026-06-28T08:05:00Z","state":"FAULT"}, ...]).
    """
    return ops.downtime_events(series, category_map, min_duration_s)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def oee_multidim(records: list, dimensions: Optional[list] = None) -> dict:
    """[READ][risk=low] Aggregate OEE across dimensions (machine × part × shift).

    Args:
        records: Labelled records — {<dimension labels>, planned_time_s, run_time_s,
            ideal_cycle_time_s, total_count, good_count}.
        dimensions: Dimension keys to group by (default ['machine','part','shift']).

    Returns dict: {dimensions, group_count, mean_oee, worst_performers:[...],
        matrix:[{dimensions, oee, oee_pct, availability, performance, quality}]}.

    Example: oee_multidim(records=[{"machine":"M1","part":"A","shift":"day",
        "planned_time_s":28800,"run_time_s":25000,"ideal_cycle_time_s":2,
        "total_count":12000,"good_count":11800}], dimensions=["machine","part"]).
    """
    return ops.oee_multidim(records, dimensions)
