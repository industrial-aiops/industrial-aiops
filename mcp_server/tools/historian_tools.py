"""Historian READ MCP tools (always exposed) — query history back OUT (A7).

The write side (``historian_push``) made TDengine / IoTDB / local SQLite data
sinks; these tools are the matching READ surface so an agent can pull real
historical windows ("what did line1.temp do in the 2h before the stop?") and
answer "what history do we actually have" (``historian_coverage``). Read-only
over the operator's OWN historian — no device I/O; the TSDB client libraries
are the same optional extras as the sinks, imported lazily.

Thin governed wrappers: the read logic lives in
``iaiops.core.sink.historian_read`` so the ``iaiops historian query|coverage``
CLI commands can call it at their OWN governed boundary instead of reaching
through these ``@governed_tool`` bodies (which would audit + budget-count the
same call twice).
"""

from typing import Optional

from iaiops.core.governance import governed_tool
from iaiops.core.sink import historian_read
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def historian_query(
    tag: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    endpoint: Optional[str] = None,
    reader: Optional[str] = None,
    limit: int = 1000,
) -> dict:
    """[READ][risk=low] Query a tag's historical samples from a historian.

    Reads history back OUT of the store the sinks write — the local SQLite
    store (~/.iaiops/data.db), TDengine, or IoTDB — so the RCA copilot / an
    agent can see real pre-incident windows instead of only short live samples.
    Read-only over the operator's OWN historian; no device I/O. Bounded: rows
    are capped and a truncation flag is set when more history exists.

    Args:
        tag: Tag/metric name as stored by historian_push (e.g. 'line1.temp').
        since/until: Optional ISO-8601 time bounds (inclusive).
        endpoint: Only samples from this endpoint label (sqlite reader only —
            the TSDB layout stores no endpoint label).
        reader: 'sqlite' | 'tdengine' | 'iotdb'. Omit to use the per-site
            'historian:' block in ~/.iaiops/config.yaml, else the local sqlite
            store. TSDB readers need their extra: pip install iaiops[tdengine|iotdb].
        limit: Max rows returned (1..10000; default 1000).

    Returns dict: {reader, source, tag, since, until, rows,
        samples:[{ts, endpoint, protocol, tag, value, quality, unit}], truncated}
        plus the standard return envelope (items_returned, items_total,
        items_total_is_exact, is_truncated, truncation_note). Trust
        `is_truncated`: an empty `samples` with is_truncated=false means the
        history really is empty, NOT that the result was cut short.

    Example: historian_query(tag="line1.temp", since="2026-07-02T06:00:00Z",
        until="2026-07-02T08:00:00Z").
    """
    return historian_read.query_history(
        tag=tag, since=since, until=until, endpoint=endpoint, reader=reader, limit=limit
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def historian_coverage(
    reader: Optional[str] = None,
    limit: int = 500,
) -> dict:
    """[READ][risk=low] Per-tag history coverage — what history do we actually have.

    Answers the question every RCA starts with: which tags have stored history,
    how many rows, and over what time span — per tag {rows, first_ts, last_ts}
    from the same store historian_push writes. Read-only, bounded (tag list is
    capped with a truncation flag); no device I/O.

    Args:
        reader: 'sqlite' | 'tdengine' | 'iotdb'. Omit to use the per-site
            'historian:' block in ~/.iaiops/config.yaml, else the local sqlite
            store. TSDB readers need their extra: pip install iaiops[tdengine|iotdb].
        limit: Max tags returned (1..2000; default 500).

    Returns dict: {reader, source, tag_count, tags:[{tag, rows, first_ts,
        last_ts}], truncated} plus the standard return envelope
        (items_returned, items_total, items_total_is_exact, is_truncated,
        truncation_note).

    Example: historian_coverage().
    """
    return historian_read.coverage(reader=reader, limit=limit)
