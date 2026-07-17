"""OEE / downtime analytics MCP tools (READ-ONLY, protocol-agnostic).

All analytics are non-destructive (risk_level='low') and operate over provided /
collected inputs, so they need no live plant. Structured JSON for agent visuals.
"""

from typing import Any, Optional

from iaiops.core.brain import energy as en
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
    breakdown_time_s: Optional[float] = None,
    setup_time_s: Optional[float] = None,
    minor_stop_time_s: Optional[float] = None,
    startup_reject_count: Optional[float] = None,
    actual_kwh: Optional[float] = None,
    baseline_kwh: Optional[float] = None,
    emission_factor_kg_per_kwh: Optional[float] = None,
    energy_tolerance: float = en.DEFAULT_ENERGY_TOLERANCE,
) -> dict:
    """[READ][risk=low] OEE = Availability × Performance × Quality (+ loss/energy depth).

    Args:
        planned_time_s: Planned production time (seconds).
        run_time_s: Actual running time (seconds) — planned minus downtime.
        ideal_cycle_time_s: Ideal/nameplate cycle time per part (seconds).
        total_count: Total parts produced.
        good_count: Good (non-reject) parts produced.
        breakdown_time_s: Optional — unplanned-stop seconds (splits availability loss).
        setup_time_s: Optional — changeover/setup seconds (splits availability loss).
        minor_stop_time_s: Optional — minor-stop seconds (splits performance loss;
            the remainder is speed loss).
        startup_reject_count: Optional — startup/warm-up rejects (splits quality
            loss; the remainder is production rejects).
        actual_kwh: Optional — measured energy for this run; enables the energy block.
        baseline_kwh: Optional — expected/baseline energy for the actual-vs-baseline
            deviation verdict.
        emission_factor_kg_per_kwh: Optional — carbon factor (kg CO2e/kWh). Default is
            a flagged placeholder (see the tool's carbon note); pass the grid's value.
        energy_tolerance: ± band (fraction) for the over/under/on-target verdict.

    Returns dict: OEE factors + oee/oee_pct + inputs + losses, plus
        ``six_big_losses`` (breakdown/setup/minor-stops/speed/startup/production-reject
        time-ladder that sums with OEE to 100%) and, when ``actual_kwh`` is given,
        ``energy`` (kwh_per_unit, carbon, and baseline deviation).

    Example: oee_compute(planned_time_s=28800, run_time_s=25200,
        ideal_cycle_time_s=2.0, total_count=12000, good_count=11800,
        setup_time_s=1800, actual_kwh=940, baseline_kwh=880).
    """
    result = ops.oee_compute(
        planned_time_s, run_time_s, ideal_cycle_time_s, total_count, good_count
    )
    result = {
        **result,
        "six_big_losses": ops.six_big_losses(
            planned_time_s,
            run_time_s,
            ideal_cycle_time_s,
            total_count,
            good_count,
            breakdown_time_s,
            setup_time_s,
            minor_stop_time_s,
            startup_reject_count,
        ),
    }
    if actual_kwh is not None:
        energy_block = en.energy_intensity(actual_kwh, good_count, emission_factor_kg_per_kwh)
        if baseline_kwh is not None:
            energy_block = {
                **energy_block,
                "baseline": en.energy_baseline_deviation(
                    actual_kwh, baseline_kwh, energy_tolerance
                ),
            }
        result = {**result, "energy": energy_block}
    return result


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def downtime_events(
    series: list[dict[str, Any]],
    category_map: Optional[dict[str, str]] = None,
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
def oee_multidim(
    records: list[dict[str, Any]],
    dimensions: Optional[list[str]] = None,
    emission_factor_kg_per_kwh: Optional[float] = None,
    energy_tolerance: float = en.DEFAULT_ENERGY_TOLERANCE,
) -> dict:
    """[READ][risk=low] Aggregate OEE (+ optional energy) across dimensions.

    Args:
        records: Labelled records — {<dimension labels>, planned_time_s, run_time_s,
            ideal_cycle_time_s, total_count, good_count} plus optional actual_kwh /
            baseline_kwh to enable the energy rollup.
        dimensions: Dimension keys to group by (default ['machine','part','shift']);
            use ['shift'] for the classic by-shift energy comparison.
        emission_factor_kg_per_kwh: Optional carbon factor (kg CO2e/kWh); default is a
            flagged placeholder — pass the grid's published value.
        energy_tolerance: ± band (fraction) for the actual-vs-baseline verdict.

    Returns dict: {dimensions, group_count, mean_oee, worst_performers:[...],
        matrix:[{dimensions, oee, oee_pct, availability, performance, quality,
        energy?}]}. When any record carries energy, adds an ``energy_baseline`` block
        that flags cross-group deviation anomalies (tolerance + robust-outlier rules).

    Example: oee_multidim(records=[{"shift":"day","planned_time_s":28800,
        "run_time_s":25000,"ideal_cycle_time_s":2,"total_count":12000,
        "good_count":11800,"actual_kwh":940,"baseline_kwh":880}], dimensions=["shift"]).
    """
    return ops.oee_multidim(records, dimensions, emission_factor_kg_per_kwh, energy_tolerance)
