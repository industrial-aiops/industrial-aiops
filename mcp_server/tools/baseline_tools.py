"""Conservative baseline MCP tools — "change-log baseline", NOT anomaly detection.

Four low-risk brain tools over the LOCAL SQLite history (``~/.iaiops/data.db``)
and the owner-only baseline store (``~/.iaiops/baselines.json``). No device I/O
anywhere: ``baseline_learn``/``baseline_check`` read data the operator already
collected; ``baseline_record_change`` writes only local metadata (an operator
change-log entry), never an OT point.

Design constraint (docs/MARKET-INSIGHTS.md R6): anomaly detection is noise
unless zero-false-positive. So learning REFUSES thin history, checking flags
only sustained excursions beyond the band by a conservative MAD margin, and
every flag cites the baseline samples it was judged against. Silent by default.
"""

from typing import Any, Optional

from iaiops.core.brain import baseline_store as bls
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_learn(tag: str, endpoint: Optional[str] = None, since: Optional[str] = None) -> dict:
    """[READ][risk=low] Learn a conservative per-tag normal band from local history.

    Source is ~/.iaiops/data.db — the local store written by
    historian_push(sink="sqlite") — NOT a live device read. Learns robust
    percentiles (p1/p99 + median/MAD, no ML) from the tag's own samples,
    segmented at the latest change recorded via baseline_record_change (the band
    reflects only the post-change regime). REFUSES with an explicit
    insufficient_data verdict (listing exactly what is missing) below 100 usable
    samples or under 24h of span — it never invents a band from thin data. On
    success the band is persisted to ~/.iaiops/baselines.json (owner-only local
    metadata, not an OT write).

    Args:
        tag: Tag name to learn, e.g. 'line1.temp'.
        endpoint: Only samples from this endpoint label.
        since: Only samples at/after this ISO-8601 time.

    Returns dict: {status: 'ok'|'insufficient_data', tag, band:{p1,p99,median,mad},
        n_samples, window:{from_ts,to_ts,span_s}, segment, missing?:[...], note}.

    Example: baseline_learn(tag="line1.temp", since="2026-06-01T00:00:00").
    """
    return bls.learn_flow(tag, endpoint=endpoint, since=since)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_check(tag: str, endpoint: Optional[str] = None, window_s: float = 3600.0) -> dict:
    """[READ][risk=low] Check recent local samples against the learned baseline.

    Reads the last window_s seconds from ~/.iaiops/data.db (no device I/O) and
    judges them against the stored band. Conservative by design: a violation is
    reported ONLY when values are beyond p1/p99 by more than 3×MAD AND sustained
    for >=3 consecutive samples — a single spike is never flagged. Every
    violation cites the baseline window (from/to ts, n samples), the band
    values, and the offending samples' timestamps/values. No stored baseline →
    an explicit no_baseline answer (never a guess). Bounded output (<=10
    violations, <=20 cited samples each).

    Args:
        tag: Tag name to check, e.g. 'line1.temp'.
        endpoint: Only samples from this endpoint label.
        window_s: Recent window to check, seconds (60..604800; default 3600).

    Returns dict: {status: 'ok'|'violation'|'no_baseline', tag, checked_samples,
        thresholds, baseline_citation, violations:[{direction, from_ts, to_ts,
        consecutive_samples, samples:[{ts,value}], baseline}], note}.

    Example: baseline_check(tag="line1.temp", window_s=7200).
    """
    return bls.check_flow(tag, endpoint=endpoint, window_s=window_s)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_record_change(tag: str, note: str) -> dict:
    """[READ][risk=low] Record an operator change-log entry for a tag (local only).

    Writes ONLY local metadata (~/.iaiops/baselines.json, owner-only) — never an
    OT device write, hence risk=low. A recorded change (setpoint moved, valve
    replaced, probe swapped) marks a regime boundary: the next baseline_learn
    uses only samples AFTER the latest change, so the band never mixes
    pre-change and post-change behavior. This operator change log — not a
    black-box score — is what makes the baseline trustworthy.

    Args:
        tag: Tag whose process changed, e.g. 'line1.temp'.
        note: What changed (required), e.g. 'setpoint 60→70C'.

    Returns dict: {tag, change:{ts, note}, changes_recorded}.

    Example: baseline_record_change(tag="line1.temp", note="setpoint 60→70C").
    """
    return bls.record_change(tag, None, note)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_status(tag: Optional[str] = None) -> dict:
    """[READ][risk=low] Baseline status for one tag, or a bounded listing of all.

    Read from the local store only (no history scan, no device I/O) and never
    guesses: 'no_baseline' (nothing learned, no refused attempt), 'learning'
    (last learn refused — still accumulating history), 'ok' (band learned, last
    check clean), 'violation' (last check flagged a sustained excursion). With
    no tag, lists every tracked tag (bounded to 100 entries).

    Args:
        tag: Optional tag name; omit to list all tracked tags.

    Returns dict: {tag, status, band?, baseline_window?, changes_recorded?, ...}
        for one tag, or {tracked_tags, listed, truncated, tags:[...]} for all.

    Example: baseline_status(tag="line1.temp").
    """
    return bls.status_flow(tag)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_learn_contextual(
    samples: list[dict[str, Any]],
    tag: str,
    context_key: str = "context",
    min_samples: int = 100,
    min_span_s: float = 86_400.0,
) -> dict:
    """[READ][risk=low] Learn one conservative band per declared context, not one per tag.

    One band per tag is wrong the moment a tag has more than one normal. A dryer
    running recipe A at 180 °C and recipe B at 240 °C gets a band spanning both,
    after which neither regime can go wrong — the band is too wide to catch a
    real excursion and too mixed to mean anything. OT normal ranges move with
    shift, product/recipe, and start-up versus steady state.

    **The context is declared, never inferred** (D16). Each sample carries a
    label under `context_key`; nothing here guesses which shift a timestamp falls
    in or clusters values into regimes it then treats as real. Each context is
    handed to the same learner as a global baseline, so it refuses on the same
    terms — a thin context is left without a band rather than borrowing another
    context's samples. Samples with no label are counted and named, not pooled
    into a default bucket, because a default bucket is that same fallback.

    Pass samples in (as with `spc_check` / `tag_health`). The local store's
    `samples` table has no context column, so there is deliberately no
    `iaiops baseline learn --context` yet; wiring one is a schema change and is
    not done.

    Args:
        samples: [{ts, value, quality?, tag?, <context_key>}] rows.
        tag: The tag being learned.
        context_key: Field that declares the context (default "context").
        min_samples: Per-context minimum before a band is learned (default 100).
        min_span_s: Per-context minimum history span in seconds (default 86400).

    Returns dict: {tag, context_key, contexts:{label: learn_baseline result},
        learned_contexts, refused_contexts, uncontexted_samples, note}.

    Example: baseline_learn_contextual(samples=[{"ts":"...","value":181.0,
        "context":"recipe-A"}], tag="dryer.temp").
    """
    from iaiops.core.brain.baseline_context import learn_contextual_baselines

    return learn_contextual_baselines(
        samples, tag, context_key=context_key, min_samples=min_samples, min_span_s=min_span_s
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_check_in_context(
    samples: list[dict[str, Any]],
    contextual: dict[str, Any],
    context: str,
    margin_mad: float = 3.0,
    sustain_n: int = 3,
) -> dict:
    """[READ][risk=low] Check readings against the band for ONE declared context.

    A reading whose context was never learned comes back `unknown_context` and
    stops there. It is **not** compared against the global band or the nearest
    one, and that refusal is the entire point of the tool: borrowing a band turns
    "we have never seen this regime" into "this regime is normal" — a silent
    pass, in the direction nobody reports. The response lists the contexts that
    do have bands so the gap is actionable.

    Otherwise the usual conservative rules apply: a violation needs values beyond
    the band by more than `margin_mad` × MAD AND sustained over `sustain_n`
    consecutive samples, and every flag cites the baseline it was judged against.

    Args:
        samples: [{ts, value, ...}] readings to check.
        contextual: A `baseline_learn_contextual` result.
        context: Which declared context these readings belong to.
        margin_mad: MAD margin beyond the band before flagging (default 3.0).
        sustain_n: Consecutive samples required (default 3 — no single-spike flags).

    Returns dict (known context): the `baseline_check` shape plus {context,
        context_key}. (unknown): {status:"unknown_context", tag, context,
        known_contexts, checked_samples, reason, note}.

    Example: baseline_check_in_context(samples=[...], contextual={...}, context="recipe-B").
    """
    from iaiops.core.brain.baseline_context import check_in_context

    return check_in_context(
        samples, contextual, context, margin_mad=margin_mad, sustain_n=sustain_n
    )
