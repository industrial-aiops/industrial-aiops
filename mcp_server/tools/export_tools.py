"""Queryability MCP tools (always exposed) — export the local SQLite sink.

``export_data`` reads the LOCAL store (``~/.iaiops/data.db``, written by
``historian_push(sink="sqlite")``) and writes an open-format file (CSV / SQLite /
Parquet) for Excel / Power BI / SQL, returning the path + row count and a
BOUNDED inline preview (never more than 200 rows). Read-only over data the
operator already collected — no device I/O.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from iaiops.core.governance import governed_tool
from iaiops.core.governance.paths import ops_path
from iaiops.core.sink.export import EXPORT_FORMATS, FORMAT_EXTENSIONS, export_samples
from iaiops.core.sink.sqlite_local import SampleFilter, query_samples
from mcp_server._shared import mcp, tool_errors

MAX_INLINE_ROWS = 200
MAX_TOOL_LIMIT = 100_000


def _default_out_path(fmt: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ops_path("exports", f"iaiops-export-{stamp}.{FORMAT_EXTENSIONS[fmt]}")


# Deliberately NOT egress=True, stated explicitly because "export" sounds like
# data leaving and a future reader will second-guess it: this reads the LOCAL
# SQLite store and writes a LOCAL file under ~/.iaiops/exports. No socket, no
# caller-named destination — the bytes never leave the box, so withholding it
# under IAIOPS_NO_EGRESS would cost the operator their own offline workflow and
# buy no confidentiality. Getting them off the box afterwards is scp's problem,
# and a host-level one. Same call for compliance_evidence_bundle (local zip).
@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def export_data(
    fmt: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    endpoint: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 10_000,
    out_path: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Export collected samples from the LOCAL SQLite sink to a file.

    Source is ~/.iaiops/data.db — the local queryable store written by
    historian_push(sink="sqlite") — NOT a live device read. Writes csv (Excel),
    sqlite (SQL browser / Power BI) or parquet (pandas/Spark; needs
    pip install 'iaiops[export]'), and returns the file path + row count with a
    bounded inline preview (first 200 rows max) so the response never floods.

    Args:
        fmt: 'csv' | 'sqlite' | 'parquet'.
        since/until: Optional ISO-8601 time bounds (inclusive).
        endpoint: Only samples from this endpoint label.
        tag: Only samples for this tag.
        limit: Max rows exported (1..100000; default 10000).
        out_path: Output file; default ~/.iaiops/exports/iaiops-export-<ts>.<ext>.

    Returns dict: {format, path, rows, preview_rows:[{ts, endpoint, protocol, tag,
        value, quality, unit}] (≤200), preview_truncated}.

    Example: export_data(fmt="csv", tag="line1.temp", since="2026-07-01T00:00:00").
    """
    kind = (fmt or "").strip().lower()
    if kind not in EXPORT_FORMATS:
        raise ValueError(f"Unknown format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}.")
    if not 1 <= int(limit) <= MAX_TOOL_LIMIT:
        raise ValueError(f"limit must be 1..{MAX_TOOL_LIMIT} (got {limit}).")
    target = Path(out_path).expanduser() if out_path else _default_out_path(kind)
    result = export_samples(
        kind,
        target,
        since=since,
        until=until,
        endpoint=endpoint,
        tag=tag,
        limit=int(limit),
    )
    preview = query_samples(
        SampleFilter(
            since=since,
            until=until,
            endpoint=endpoint,
            tag=tag,
            limit=min(int(limit), MAX_INLINE_ROWS),
        ),
    )
    return {
        **result,
        "preview_rows": preview,
        "preview_truncated": result["rows"] > len(preview),
    }
