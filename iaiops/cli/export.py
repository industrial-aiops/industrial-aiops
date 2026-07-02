"""``iaiops export`` — get collected data OUT (CSV / SQLite / Parquet).

Reads the LOCAL SQLite sink (``~/.iaiops/data.db``, written by
``historian push --sink sqlite`` / ``historian_push(sink="sqlite")``) and writes
an open-format file for Excel / Power BI / SQL. Parquet needs the optional
``iaiops[export]`` extra (pyarrow); CSV and SQLite are stdlib-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from iaiops.cli._common import cli_errors
from iaiops.core.sink.export import EXPORT_FORMATS, FORMAT_EXTENSIONS, export_samples

console = Console()


@cli_errors
def export_cmd(
    fmt: str = typer.Argument(..., help=f"Output format: {' | '.join(EXPORT_FORMATS)}"),
    out: Path | None = typer.Option(
        None, "--out", "-o",
        help="Output file (default: ./iaiops-export.<ext>)",
    ),
    since: str | None = typer.Option(
        None, "--since", help="Only samples at/after this ISO-8601 time"
    ),
    until: str | None = typer.Option(
        None, "--until", help="Only samples at/before this ISO-8601 time"
    ),
    endpoint: str | None = typer.Option(
        None, "--endpoint", "-e", help="Only samples from this endpoint"
    ),
    tag: str | None = typer.Option(None, "--tag", help="Only samples for this tag"),
    limit: int = typer.Option(
        10_000, "--limit", help="Max rows to export (1..1000000)"
    ),
) -> None:
    """Export collected samples from the LOCAL SQLite sink to an open format.

    Source: ~/.iaiops/data.db — the local queryable store written by
    'iaiops historian push --sink sqlite' (or the historian_push MCP tool with
    sink="sqlite"). Formats: csv (Excel), sqlite (any SQL browser / Power BI),
    parquet (pandas / Spark — needs the pyarrow "export" extra:
    pip install "iaiops\\[export]").
    """
    kind = (fmt or "").strip().lower()
    if kind not in EXPORT_FORMATS:
        raise ValueError(
            f"Unknown format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}."
        )
    target = out or Path(f"iaiops-export.{FORMAT_EXTENSIONS[kind]}")
    result = export_samples(
        kind, target, since=since, until=until, endpoint=endpoint, tag=tag, limit=limit
    )
    console.print_json(json.dumps(result, default=str))


__all__ = ["export_cmd"]
