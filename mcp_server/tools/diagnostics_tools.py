"""Cross-protocol intelligent-troubleshooting MCP tools (READ-ONLY).

All diagnostics are non-destructive (risk_level='low'). They return structured,
multi-dimensional JSON designed for an agent to visualize.
"""

from typing import Optional

from iaiops.core.brain import diagnostics as diag
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def diagnose_dataflow(
    endpoint: Optional[str] = None,
    ref: Optional[str] = None,
    freshness_threshold_s: int = 60,
    series: Optional[list] = None,
    flatline_eps: float = 1e-9,
) -> dict:
    """[READ][risk=low] Localize a 'no data' break across an endpoint's reachable hops.

    Probes connect → read(ref) → freshness → variance and returns a verdict with
    per-hop detail and a recommended action. The #1 OT triage: distinguishes
    "cannot connect" (network/PLC down) from "comms OK but value stale"
    (upstream/field/source) from "good status but flatline" (sensor stuck).

    Args:
        endpoint: Endpoint name from config (any protocol).
        ref: Tag/node/address/device to read (OPC-UA node id, Modbus address,
            S7 address string, MELSEC device). Omit to test connectivity only.
        freshness_threshold_s: Max value-age (seconds) before 'stale' (default 60).
        series: Optional injected samples (scalars or {value,timestamp}) for
            flatline/variance reasoning when a live historian is out of reach.
        flatline_eps: Spread at/below which a series counts as flatline.

    Returns dict: {verdict ('cannot_connect'|'comms_ok_value_unreadable'|
        'comms_ok_bad_quality'|'comms_ok_value_stale'|'comms_ok_flatline'|
        'healthy'), diagnosis, recommended_action, hops:[{hop, ok, detail}]}.

    Example: diagnose_dataflow(endpoint="line1", ref="ns=2;i=5", freshness_threshold_s=30).
    """
    return diag.diagnose_dataflow(
        _target(endpoint), ref, freshness_threshold_s, series, flatline_eps
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def historian_health(
    series: list, gap_threshold_s: float = 60.0, flatline_eps: float = 1e-9
) -> dict:
    """[READ][risk=low] Bad-tag / flatline / gap detection over a provided series.

    Pure analysis over an injected sample series — no live historian needed.

    Args:
        series: Samples — scalars or {value, timestamp (ISO-8601), quality|good}.
        gap_threshold_s: Time gap (seconds) between consecutive samples that counts
            as a data gap (default 60).
        flatline_eps: Spread at/below which the series counts as flatline.

    Returns dict: {samples, numeric_samples, bad_quality_count, flatline (bool),
        gap_count, gaps:[{after, gap_seconds}], stdev,
        verdict ('ok'|'degraded'|'gappy'|'flatline'|'bad_tag')}.

    Example: historian_health(series=[{"value":10,"timestamp":"2026-06-28T10:00:00Z"}, ...]).
    """
    return diag.historian_health(series, gap_threshold_s, flatline_eps)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alarm_bad_actors(
    events: list,
    window_minutes: Optional[float] = None,
    chatter_window_s: float = 60.0,
    standing_s: float = 86400.0,
    top_n: int = 10,
) -> dict:
    """[READ][risk=low] ISA-18.2 alarm-flood analysis over a list of alarm events.

    Args:
        events: Alarm/condition events — {source, timestamp (ISO-8601), priority?,
            state? (ACTIVE/RTN/ACK)}.
        window_minutes: Analysis window; omitted → inferred from event timestamps.
        chatter_window_s: A source with >=3 transitions inside this window chatters.
        standing_s: An alarm active longer than this is 'standing/stale' (default 24h).
        top_n: How many top offenders to return.

    Returns dict: {event_count, window_minutes, alarms_per_hour,
        isa_18_2:{ok_max:6, manageable_max:12, flood_min:30},
        flood_verdict ('ok'|'manageable'|'over_target'|'flood'),
        priority_distribution, pareto_sources_for_80pct, top_offenders:[{source,
        count, share_pct, chattering, standing}], chattering:[...], standing:[...]}.

    Example: alarm_bad_actors(events=[{"source":"FIC101","timestamp":"...",
        "priority":"high"}, ...]).
    """
    return diag.alarm_bad_actors(events, window_minutes, chatter_window_s, standing_s, top_n)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def tag_health(tags: list, thresholds: Optional[dict] = None) -> dict:
    """[READ][risk=low] Rank tag offenders by bad-quality / flatline / range / anomaly.

    Args:
        tags: Per-tag dicts — {ref, label?, samples:[scalars or {value, good|quality}],
            warn_high?, alarm_high?, warn_low?, alarm_low?}.
        thresholds: Optional {ref: {warn_high, alarm_high, warn_low, alarm_low}} override.

    Returns dict: {evaluated, overall ('ok'|'warn'|'alarm'), offender_count,
        offenders:[{ref, label, samples, latest, flags:[...], anomaly_count,
        severity (0..3)}], results:[...]}. Flags include bad_quality, flatline,
        out_of_range_warn/alarm, statistical_anomaly.

    Example: tag_health(tags=[{"ref":"ns=2;i=5","samples":[70,71,70,99]}]).
    """
    return diag.tag_health(tags, thresholds)
