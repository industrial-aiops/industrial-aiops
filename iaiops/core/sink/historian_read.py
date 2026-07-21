"""Historian READ logic — query history back OUT of a sink (A7), governance-free.

The write side (``historian_push``) makes TDengine / IoTDB / local SQLite data
sinks; these functions are the matching READ side. They live in ``core`` (not in
the MCP tool module) so BOTH front-ends can call them at their own boundary
without one reaching through the other's ``@governed_tool`` wrapper — which would
audit and budget-count the same call twice. Read-only over the operator's OWN
historian; no device I/O. The TSDB client libraries are the same optional extras
as the sinks, imported lazily by the reader.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import load_config_env
from iaiops.core.runtime.envelope import envelope_fields
from iaiops.core.sink.reader import SUPPORTED_READERS, HistorianReader, get_reader
from iaiops.core.sink.sqlite_local import SampleFilter

MAX_TOOL_ROWS = 10_000
MAX_COVERAGE_TAGS = 2_000


def _resolve_reader(reader: str | None) -> tuple[str, HistorianReader]:
    """Pick the reader: explicit arg > per-site ``historian:`` block > sqlite.

    Connection opts come from the config block when it matches the chosen
    reader (password from the encrypted store); otherwise the reader's
    defaults apply (sqlite = the local ``~/.iaiops/data.db`` store).
    """
    hist = load_config_env().historian
    name = (reader or "").strip().lower() or (hist.reader if hist else "sqlite")
    if name not in SUPPORTED_READERS:
        # ValueError so the callers' error harnesses pass the teaching message through.
        raise ValueError(
            f"Unknown historian reader '{name}'. Supported: {', '.join(SUPPORTED_READERS)}."
        )
    opts = hist.reader_opts() if (hist and hist.reader == name) else {}
    return name, get_reader(name, **opts)


def _close(adapter: HistorianReader) -> None:
    try:
        adapter.close()
    except Exception:  # noqa: BLE001 — close is best-effort
        pass


def query_history(
    tag: str,
    since: str | None = None,
    until: str | None = None,
    endpoint: str | None = None,
    reader: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Query a tag's historical samples from a historian (read-only, bounded)."""
    if not (tag or "").strip():
        raise ValueError("tag is required (the metric name historian_push stored).")
    if not 1 <= int(limit) <= MAX_TOOL_ROWS:
        raise ValueError(f"limit must be 1..{MAX_TOOL_ROWS} (got {limit}).")
    name, adapter = _resolve_reader(reader)
    try:
        # Pull one extra row so truncation is an honest flag, not a guess.
        rows = adapter.query(
            SampleFilter(
                since=since,
                until=until,
                endpoint=endpoint,
                tag=tag.strip(),
                limit=int(limit) + 1,
            )
        )
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
        # Legacy bool, kept for published-consumer compatibility. `is_truncated`
        # from the envelope below is the key a reader should trust.
        "truncated": truncated,
        # limit+1 probe: the exact upstream total is unknown, so say so rather
        # than reporting the page size as if it were the total.
        **envelope_fields(returned=len(samples), more_available=truncated),
    }


def coverage(reader: str | None = None, limit: int = 500) -> dict[str, Any]:
    """Per-tag history coverage — row counts + first/last timestamps (read-only)."""
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
        "truncated": truncated,  # legacy bool — see `is_truncated`
        "supported_readers": list(SUPPORTED_READERS),
        **envelope_fields(returned=len(tags), more_available=truncated),
    }
