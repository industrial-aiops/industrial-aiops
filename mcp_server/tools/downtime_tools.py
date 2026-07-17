"""Downtime triage copilot MCP tool (READ-ONLY).

Composes the three downtime lenses — alarm cascade (first-out root), RCA
(cited causal verdict), and PdM forecasts (pre-incident precursors) — into a
single triage, and cross-checks whether the first-out alarm agrees with the
RCA's primary cause. Advisory only; nothing is executed. The heavy lifting is
pure (:mod:`iaiops.core.brain.downtime_copilot`); this tool just injects the
optional per-site historian bundle, exactly as ``downtime_root_cause`` does.
"""

from typing import Any, Optional

from iaiops.core.brain import downtime_copilot as copilot
from iaiops.core.brain import rca_history
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def downtime_triage(
    window: dict[str, Any],
    alarms: Optional[list[dict[str, Any]]] = None,
    tags: Optional[list[dict[str, Any]]] = None,
    dataflow: Optional[dict[str, Any]] = None,
    state_series: Optional[list[dict[str, Any]]] = None,
    precursors: Optional[list[dict[str, Any]]] = None,
    cascade_window_s: float = 60.0,
    lead_window_s: float = 300.0,
    cause_weights: Optional[dict[str, float]] = None,
    imminent_within_s: float = 86400.0,
    include_graph: bool = False,
) -> dict:
    """[READ][risk=low] One-call downtime triage: first-look alarm + RCA cause + precursors.

    Answers the operator's three simultaneous questions on a stopped line — which
    alarm to look at first, the likely cause, and whether anything warned us —
    then cross-checks whether the first-out alarm agrees with the RCA verdict.
    Composes alarm_cascade + downtime_root_cause + pdm_forecast over ONE incident;
    every field traces to a sub-report echoed under 'cascade'/'rca'/
    'precursor_forecasts'. Read-first and advisory: it proposes but executes
    nothing. Thin evidence downgrades honestly rather than guessing.

    Args:
        window: {start (ISO-8601), end?, asset?, category?}. If 'end' is omitted
            but state_series is given, the first running→stopped span bounds it.
        alarms: Alarm/condition events — {source, timestamp, message?, priority?,
            state?}. Feeds BOTH the first-out cascade and the RCA.
        tags: Per-tag samples — {ref, samples:[...], warn_high?, ...} (via tag_health).
        dataflow: A diagnose_dataflow result dict (localizes comms vs field).
        state_series: {timestamp, state} samples to bound the window if 'end' is absent.
        precursors: Signals to check for a pre-incident trend — [{signal, series:
            [scalars or {value, timestamp}], warn_high?, alarm_high?, warn_low?,
            alarm_low?}]; each is run through pdm_forecast and kept only when it was
            degrading/imminent before the trip.
        cascade_window_s: Quiet gap (s) separating alarm cascades (default 60).
        lead_window_s: Causal lead window before onset (default 300s).
        cause_weights: Optional per-site {cause: multiplier} RCA override.
        imminent_within_s: ETA horizon that marks a precursor 'imminent' (default 24h).
        include_graph: When true, the echoed 'rca' sub-report also carries a 'graph'
            block — the SAME verdict re-projected as a causal graph {nodes, edges,
            mermaid, meta} (signal → cause → downtime) for a frontend. Pure re-shape;
            no new reasoning. Omit to keep the flat rca summary (default).

    Returns dict: {window, triage:{first_look:{source, ts, cascade_size, basis},
        likely_cause:{cause, verdict, confidence, confidence_band,
        recommended_action}, cross_check:{status ('corroborated'|'diverging'|
        'no_alarm_root'|'no_rca_primary'), detail}, precursors_missed:[{signal,
        status, direction, eta_to_limit, unit, limit}], recommended_next_data},
        cascade:{...}, rca:{verdict, primary_cause, top_hypotheses, graph?},
        precursor_forecasts:[...], anti_hallucination}.

    Example: downtime_triage(window={"start":"2026-06-28T10:00:00Z","asset":"line1"},
        alarms=[{"source":"M1_DRIVE","timestamp":"2026-06-28T09:59:50Z",
                 "message":"motor overload trip"}],
        precursors=[{"signal":"M1_temp","series":[...],"warn_high":80}]).
    """
    refs = [t.get("ref") for t in (tags or []) if isinstance(t, dict) and t.get("ref")]
    historian = rca_history.gather_pre_incident(window, refs or None)
    return copilot.downtime_triage(
        window,
        alarms=alarms,
        tags=tags,
        dataflow=dataflow,
        state_series=state_series,
        precursors=precursors,
        cascade_window_s=cascade_window_s,
        lead_window_s=lead_window_s,
        cause_weights=cause_weights,
        historian=historian,
        imminent_within_s=imminent_within_s,
        include_graph=include_graph,
    )
