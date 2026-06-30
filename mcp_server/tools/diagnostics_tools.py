"""Cross-protocol intelligent-troubleshooting MCP tools (READ-ONLY).

All diagnostics are non-destructive (risk_level='low'). They return structured,
multi-dimensional JSON designed for an agent to visualize.
"""

from typing import Optional

from iaiops.core.brain import dataquality as dq
from iaiops.core.brain import diagnostics as diag
from iaiops.core.brain import rca as rca_brain
from iaiops.core.brain import rca_collect, rca_weights
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


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def subscription_health(
    sequence: list,
    republish_requested: int = 0,
    republish_rejected: int = 0,
    tags_per_channel: Optional[dict] = None,
    max_tags_per_channel: int = 5000,
    wrap_at: Optional[int] = None,
) -> dict:
    """[READ][risk=low] Health of a sequenced subscription feed (OPC-UA or Sparkplug B).

    Detects dropped notifications (sequence gaps), duplicates / out-of-order, a high
    republish-rejection rate, and overloaded channels — the classic Kepware
    "too many tags on one channel → republish/queue-flush dropouts" fault.

    Args:
        sequence: Sequence numbers actually received, in arrival order.
        republish_requested: How many republish requests were made.
        republish_rejected: How many were rejected (server couldn't keep up).
        tags_per_channel: {channel/endpoint: tag_count} — flags channels over the max.
        max_tags_per_channel: Density above which a channel is flagged (default 5000).
        wrap_at: Modulus for rolling counters (e.g. 256 for Sparkplug B seq); omit
            for monotonic OPC-UA counters.

    Returns dict: {received, missed_count, duplicate_count, out_of_order_count,
        republish_requested, republish_rejected, republish_reject_rate,
        overloaded_channels:[{channel, tags}], max_tags_per_channel,
        verdict ('ok'|'reordered'|'lossy'|'overloaded'), recommendation}.

    Example: subscription_health(sequence=[1,2,4,5], tags_per_channel={"ch1":7000}).
    """
    return diag.subscription_health(
        sequence,
        republish_requested,
        republish_rejected,
        tags_per_channel,
        max_tags_per_channel,
        wrap_at,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def downtime_root_cause(
    window: dict,
    alarms: Optional[list] = None,
    tags: Optional[list] = None,
    dataflow: Optional[dict] = None,
    state_series: Optional[list] = None,
    lead_window_s: float = 300.0,
    cause_weights: Optional[dict] = None,
) -> dict:
    """[READ][risk=low] AI downtime root-cause copilot — cited verdict, ADVISORY only.

    Correlates whatever evidence you supply around a downtime/incident window —
    alarm events, tag samples, a diagnose_dataflow verdict, a machine-state series —
    ranks candidate root causes, and cites the REAL signals behind each. Read-first:
    it proposes a human-approved, undoable (MOC-gated) action but executes nothing.
    Anti-hallucination: only signals present in the input are cited; thin evidence
    downgrades to 'insufficient_evidence' with a 'recommended_next_data' list rather
    than a confident guess. Confidence combines independent, time-correlated evidence
    (signals BEFORE onset outweigh signals during it).

    Args:
        window: {start (ISO-8601), end? (ISO-8601), asset?, category?}. If 'end' is
            omitted but state_series is given, the first running→stopped span bounds it.
        alarms: Alarm/condition events — {source, timestamp, message?, priority?, state?}.
        tags: Per-tag samples — {ref, samples:[scalars or {value, good|quality}],
            warn_high?, alarm_high?, ...} (scored via tag_health).
        dataflow: A diagnose_dataflow result dict (its 'verdict' localizes comms vs field).
        state_series: {timestamp, state} samples to bound the window if 'end' is absent.
        lead_window_s: How far before onset a signal may sit and still count as a cause
            (default 300s); signals after onset are treated as consequences.
        cause_weights: Optional per-site {cause: multiplier} override (e.g. from
            learn_cause_weights) — scales each cause's evidence (1.0 = neutral
            default) before the noisy-OR. Unknown causes / non-numeric weights are
            rejected; values are clamped. Omit for the shipped default weighting.

    Returns dict: {window, verdict ('root_cause_identified'|'multiple_candidates'|
        'insufficient_evidence'), primary_cause, hypotheses:[{cause, confidence (0..1),
        confidence_band, evidence:[{signal, ref, at?, lead_time_s?, detail, weight}],
        recommended_action}], evidence_summary, recommended_next_data?,
        anti_hallucination}.

    Example: downtime_root_cause(window={"start":"2026-06-28T10:00:00Z","asset":"line1"},
        alarms=[{"source":"M1_DRIVE","timestamp":"2026-06-28T09:59:50Z",
                 "message":"motor overload trip"}], dataflow={"verdict":"healthy"}).
    """
    return rca_brain.downtime_rca(
        window, alarms, tags, dataflow, state_series, lead_window_s, cause_weights
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def downtime_root_cause_live(
    endpoint: Optional[str] = None,
    window: Optional[dict] = None,
    refs: Optional[list] = None,
    sample_count: int = 8,
    interval_ms: int = 200,
    include_alarms: bool = True,
    lead_window_s: float = 300.0,
) -> dict:
    """[READ][risk=low] AI downtime RCA copilot that GATHERS its own live evidence.

    Same advisory, read-only, evidence-cited contract as downtime_root_cause — but
    instead of hand-injecting evidence you give an endpoint + incident window and it
    pulls the evidence itself: a cross-protocol diagnose_dataflow probe, a short
    sampled series per ref (so flatline/bad-quality/anomaly surface via tag_health),
    and active OPC-UA conditions. Light read load; non-destructive; nothing executed.
    The gathered bundle is echoed under 'collected_evidence' (no hidden inputs).

    Args:
        endpoint: Endpoint name from config (any protocol). Omit for the default.
        window: {start (ISO-8601), end?, asset?, category?, freshness_threshold_s?}.
        refs: Tags/nodes/addresses to sample for this incident (first is also the
            diagnose_dataflow target). Capped at 20.
        sample_count: Reads per ref to build its series (1..60, default 8).
        interval_ms: Delay between reads (>=50ms, default 200).
        include_alarms: Surface active OPC-UA conditions as alarm evidence (OPC-UA only).
        lead_window_s: Causal lead window before onset (default 300s).

    Returns dict: same shape as downtime_root_cause plus 'collected_evidence'
        {endpoint, protocol, refs_sampled, alarms_found, dataflow_verdict}.

    Example: downtime_root_cause_live(endpoint="line1",
        window={"start":"2026-06-28T10:00:00Z","asset":"line1"},
        refs=["ns=2;i=5","ns=2;i=6"]).
    """
    if not isinstance(window, dict) or not window.get("start"):
        return {"error": "window={start: ISO-8601, ...} is required.",
                "hint": "Pass the incident onset time as window.start."}
    return rca_collect.downtime_rca_live(
        _target(endpoint), window, refs, sample_count, interval_ms,
        include_alarms, lead_window_s,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def learn_cause_weights(
    history: list,
    min_samples: int = 8,
    smoothing: float = 1.0,
) -> dict:
    """[READ][risk=low] Learn a per-site RCA {cause: weight} profile from history.

    Derives a per-site cause-weight profile from a corpus of CONFIRMED past
    incidents so downtime_root_cause adapts to what THIS site's evidence actually
    predicts. Pure + explainable: each weight is the smoothed signal→cause
    precision relative to chance (>1 = evidence for that cause is reliable here,
    <1 = often misleading) — no black box. Anti-overfit: Laplace smoothing + a
    per-cause min-sample guard, and a fall-back to the shipped defaults when the
    corpus is too thin. Feed the returned 'cause_weights' to downtime_root_cause's
    cause_weights argument. Advisory: it tunes ranking, never executes anything.

    Args:
        history: Confirmed incidents — [{cause, signals:[...]}] where 'cause' is the
            known root cause and 'signals' are the cause labels the evidence pointed
            at (both from the copilot taxonomy: mechanical_fault, comms_loss,
            sensor_fault, material_starvation, quality_reject, changeover, utility_fault).
        min_samples: Minimum confirmed incidents before adapting at all (default 8);
            below it the defaults are kept.
        smoothing: Laplace pseudo-count pulling each estimate toward chance (default 1.0).

    Returns dict: {cause_weights:{cause: multiplier}, n_incidents, per_cause:{cause:
        {support, hits, precision, weight, note}}, rationale}.

    Example: learn_cause_weights(history=[{"cause":"mechanical_fault",
        "signals":["mechanical_fault"]}, {"cause":"comms_loss","signals":["comms_loss"]}]).
    """
    return rca_weights.learn_cause_weights(history, min_samples, smoothing)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def data_quality_scorecard(
    feeds: list, default_staleness_s: float = 300.0, now: Optional[str] = None
) -> dict:
    """[READ][risk=low] Fleet data-TRUST scorecard across endpoints' tag feeds.

    Scores each tag 0-100 on whether its data can be BELIEVED — staleness, dead
    heartbeat, bad-quality, flatline, gaps, anomaly — then rolls up per endpoint
    and across the fleet. NOT process health (it does not score whether a value is
    alarming, only whether it is trustworthy). Pure analysis over provided feeds.

    Args:
        feeds: Per-endpoint feeds — {endpoint, tags:[{ref, label?, samples:[scalars
            or {value, good|quality, timestamp?}], expected_update_s?, heartbeat?}]}.
        default_staleness_s: Max sample-age before 'stale' when a tag sets no
            expected_update_s (default 300).
        now: ISO-8601 reference time for staleness (deterministic); omit for now-UTC.

    Returns dict: {evaluated_endpoints, evaluated_tags, fleet_score (0-100),
        fleet_status, issue_breakdown{}, worst_endpoints[], worst_tags[],
        endpoints:[{endpoint, score, status, status_counts, worst_tag}]}.

    Example: data_quality_scorecard(feeds=[{"endpoint":"line1","tags":[{"ref":"hb",
        "heartbeat":true,"samples":[5,5,5,5]}]}]).
    """
    return dq.data_quality_scorecard(feeds, default_staleness_s, now)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def data_quality_fleet_rollup(
    feeds: list,
    default_staleness_s: float = 300.0,
    now: Optional[str] = None,
    top_n: int = 10,
) -> dict:
    """[READ][risk=low] Cross-endpoint fleet rollup of data-TRUST: worst tags + bad quality.

    Builds on data_quality_scorecard to give a fleet-wide view: endpoints ranked by
    their single worst tag, bad-quality tag counts aggregated across every endpoint,
    and a first-class liveness rollup (dead-heartbeat / flatline). Staleness and gap
    budgets are configurable per tag (staleness_s / gap_threshold_s) and per feed,
    so a slow daily counter is not judged like a 1Hz sensor. Pure analysis.

    Args:
        feeds: Per-endpoint feeds — {endpoint, staleness_s?, tags:[{ref, label?,
            samples:[scalars or {value, good|quality, timestamp?}], expected_update_s?,
            staleness_s?, gap_threshold_s?, flatline_after_s?, heartbeat?}]}.
        default_staleness_s: Fallback max sample-age (seconds) before 'stale' when a
            tag/feed sets no staleness_s/expected_update_s (default 300).
        now: ISO-8601 reference time for staleness (deterministic); omit for now-UTC.
        top_n: How many endpoints / bad-quality rows to return (default 10).

    Returns dict: {evaluated_endpoints, evaluated_tags, fleet_score (0-100),
        fleet_status, endpoints_ranked_by_worst_tag:[...], bad_quality_rollup:
        {total_bad_quality_tags, endpoints_affected, by_endpoint:[{endpoint,
        bad_quality_tags, fully_bad, partial_bad}]}, liveness_rollup:
        {dead_heartbeat_count, flatline_count, dead_heartbeats[], flatlines[]},
        issue_breakdown{}}.

    Example: data_quality_fleet_rollup(feeds=[{"endpoint":"line1","tags":[{"ref":"t",
        "samples":[{"value":None,"good":false}]}]}]).
    """
    return dq.data_quality_fleet_rollup(feeds, default_staleness_s, now, top_n)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def heartbeat_health(series: list, max_interval_s: Optional[float] = None) -> dict:
    """[READ][risk=low] Is a heartbeat/watchdog tag still alive? (liveness check).

    A heartbeat must keep CHANGING; a flatlined one means the upstream is dead even
    when comms/quality look fine. With timestamped samples + max_interval_s, also
    flags the longest stall.

    Args:
        series: Heartbeat samples — scalars or {value, timestamp?} (a counter/toggle).
        max_interval_s: Max allowed gap between changes; exceeding it = not alive.

    Returns dict: {alive (bool), samples, distinct_transitions, spread,
        longest_stall_s, reason}.

    Example: heartbeat_health(series=[1,2,3,4,5], max_interval_s=10).
    """
    return dq.heartbeat_health(series, max_interval_s)
