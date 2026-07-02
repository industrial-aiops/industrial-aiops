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

from typing import Optional

from iaiops.core.brain import baseline_store as bls
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def baseline_learn(
    tag: str, endpoint: Optional[str] = None, since: Optional[str] = None
) -> dict:
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
def baseline_check(
    tag: str, endpoint: Optional[str] = None, window_s: float = 3600.0
) -> dict:
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
