"""Historian READ MCP tools (always exposed) — query history back OUT (A7).

The write side (``historian_push``) made TDengine / IoTDB / local SQLite data
sinks; these tools are the matching READ surface so an agent can pull real
historical windows ("what did line1.temp do in the 2h before the stop?") and
answer "what history do we actually have" (``historian_coverage``). Read-only
over the operator's OWN historian — no device I/O; the TSDB client libraries
are the same optional extras as the sinks, imported lazily.
"""

from typing import Optional

from iaiops.core.governance import governed_tool
from iaiops.core.runtime.config import load_config_env
from iaiops.core.sink.reader import SUPPORTED_READERS, HistorianReader, get_reader
from iaiops.core.sink.sqlite_local import SampleFilter
from mcp_server._shared import mcp, tool_errors

MAX_TOOL_ROWS = 10_000
MAX_COVERAGE_TAGS = 2_000


def _resolve_reader(reader: Optional[str]) -> tuple[str, HistorianReader]:
    """Pick the reader: explicit arg > per-site ``historian:`` block > sqlite.

    Connection opts come from the config block when it matches the chosen
    reader (password from the encrypted store); otherwise the reader's
    defaults apply (sqlite = the local ``~/.iaiops/data.db`` store).
    """
    hist = load_config_env().historian
    name = (reader or "").strip().lower() or (hist.reader if hist else "sqlite")
    if name not in SUPPORTED_READERS:
        # ValueError so @tool_errors passes the teaching message through.
        raise ValueError(
            f"Unknown historian reader '{name}'. Supported: "
            f"{', '.join(SUPPORTED_READERS)}."
        )
    opts = hist.reader_opts() if (hist and hist.reader == name) else {}
    return name, get_reader(name, **opts)


def _close(adapter: HistorianReader) -> None:
    try:
        adapter.close()
    except Exception:  # noqa: BLE001 — close is best-effort
        pass


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
        samples:[{ts, endpoint, protocol, tag, value, quality, unit}], truncated}.

    Example: historian_query(tag="line1.temp", since="2026-07-02T06:00:00Z",
        until="2026-07-02T08:00:00Z").
    """
    if not (tag or "").strip():
        raise ValueError("tag is required (the metric name historian_push stored).")
    if not 1 <= int(limit) <= MAX_TOOL_ROWS:
        raise ValueError(f"limit must be 1..{MAX_TOOL_ROWS} (got {limit}).")
    name, adapter = _resolve_reader(reader)
    try:
        # Pull one extra row so truncation is an honest flag, not a guess.
        rows = adapter.query(SampleFilter(
            since=since, until=until, endpoint=endpoint, tag=tag.strip(),
            limit=int(limit) + 1,
        ))
    finally:
        _close(adapter)
    truncated = len(rows) > int(limit)
    samples = rows[: int(limit)]
    return {
        "reader": name,
        "source": f"historian:{name}",
        "tag": tag.strip(),
        "since": since,
        "until": until,
        "rows": len(samples),
        "samples": samples,
        "truncated": truncated,
    }


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
        last_ts}], truncated}.

    Example: historian_coverage().
    """
    if not 1 <= int(limit) <= MAX_COVERAGE_TAGS:
        raise ValueError(f"limit must be 1..{MAX_COVERAGE_TAGS} (got {limit}).")
    name, adapter = _resolve_reader(reader)
    try:
        rows = adapter.coverage(limit=int(limit) + 1)
    finally:
        _close(adapter)
    truncated = len(rows) > int(limit)
    tags = rows[: int(limit)]
    return {
        "reader": name,
        "source": f"historian:{name}",
        "tag_count": len(tags),
        "tags": tags,
        "truncated": truncated,
        "supported_readers": list(SUPPORTED_READERS),
    }
