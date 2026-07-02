"""``iaiops historian query|coverage`` — read history back OUT of a historian (A7).

Extends the existing ``iaiops historian`` app (whose ``push`` writes points to
TDengine / IoTDB / local SQLite) with the matching READ side: ``query`` pulls a
tag's historical window, ``coverage`` answers "what history do we actually
have" (per-tag row counts + first/last timestamps). The commands delegate to
the governed MCP tool bodies so CLI and MCP behave identically (same bounds,
same teaching errors).
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import cli_errors

console = Console()


def _emit(payload: dict) -> None:
    if isinstance(payload, dict) and "error" in payload:
        console.print_json(json.dumps(payload, default=str))
        raise typer.Exit(code=1)
    console.print_json(json.dumps(payload, default=str))


@cli_errors
def query_cmd(
    tag: str = typer.Option(..., "--tag", help="Tag/metric name (as stored)."),
    since: str = typer.Option("", "--since", help="ISO-8601 window floor (inclusive)."),
    until: str = typer.Option("", "--until", help="ISO-8601 window ceiling (inclusive)."),
    endpoint: str = typer.Option("", "--endpoint", "-e",
                                 help="Endpoint label filter (sqlite reader only)."),
    reader: str = typer.Option("", "--reader",
                               help="sqlite | tdengine | iotdb (default: the "
                                    "config 'historian:' block, else sqlite)."),
    limit: int = typer.Option(1000, "--limit", help="Max rows (1..10000)."),
) -> None:
    """Query a tag's historical samples from a historian (read-only)."""
    from mcp_server.tools.historian_tools import historian_query

    _emit(historian_query(
        tag=tag, since=since or None, until=until or None,
        endpoint=endpoint or None, reader=reader or None, limit=limit,
    ))


@cli_errors
def coverage_cmd(
    reader: str = typer.Option("", "--reader",
                               help="sqlite | tdengine | iotdb (default: the "
                                    "config 'historian:' block, else sqlite)."),
    limit: int = typer.Option(500, "--limit", help="Max tags (1..2000)."),
) -> None:
    """Per-tag history coverage: row counts + first/last timestamps (read-only)."""
    from mcp_server.tools.historian_tools import historian_coverage

    _emit(historian_coverage(reader=reader or None, limit=limit))


__all__ = ["query_cmd", "coverage_cmd"]
