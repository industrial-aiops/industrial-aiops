"""``iaiops compliance`` / ``iaiops historian`` — 信创 / China-entry commands.

``compliance`` prints the 《工控系统网络安全防护指南》 ↔ iaiops mapping (an
onboarding/sales artifact). ``historian push`` writes collected telemetry (a JSON
list of points) to a domestic TSDB (TDengine / IoTDB) — 信创 data egress.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from iaiops.cli._common import cli_errors
from iaiops.core.brain.compliance import (
    compliance_dengbao_levels,
    compliance_frameworks,
    compliance_mapping,
)
from iaiops.core.sink.push import historian_push

console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str, ensure_ascii=False))


@cli_errors
def compliance_cmd(
    frameworks: bool = typer.Option(
        False, "--frameworks", help="Print the 防护指南 ↔ 等保 2.0 ↔ IEC 62443 crosswalk instead."
    ),
    dengbao_level: str = typer.Option(
        "", "--dengbao-level",
        help="Print 等保 2.0 二级 vs 三级 per-pillar deltas (l2/l3, 二级/三级, 2/3; empty=both).",
    ),
) -> None:
    """Print the 《工控系统网络安全防护指南》 ↔ iaiops governance mapping.

    With --frameworks, print the cross-framework 对照 (等保 2.0 / IEC 62443) instead.
    With --dengbao-level, print the 等保 2.0 二级/三级 per-pillar deltas (pass a level
    to focus, or leave blank for both).
    """
    if dengbao_level:
        _emit(compliance_dengbao_levels(dengbao_level))
        return
    _emit(compliance_frameworks() if frameworks else compliance_mapping())


historian_app = typer.Typer(
    help="信创 national-TSDB historian sink (push collected telemetry to TDengine/IoTDB).",
    no_args_is_help=True,
)


@historian_app.command("push")
@cli_errors
def push_cmd(
    sink: str = typer.Option(..., "--sink", help="tdengine | iotdb"),
    input: Path = typer.Option(..., "--input", help="JSON file: list of points"),
    host: str = typer.Option("localhost", "--host"),
    port: int = typer.Option(0, "--port"),
    user: str = typer.Option("", "--user"),
    password: str = typer.Option("", "--password"),
    database: str = typer.Option("", "--database"),
) -> None:
    """Write a JSON list of collected points to a TDengine / IoTDB historian."""
    points = json.loads(Path(input).read_text("utf-8"))
    opts: dict = {"host": host}
    if port:
        opts["port"] = port
    if user:
        opts["user"] = user
    if password:
        opts["password"] = password
    if database:
        opts["database"] = database
    _emit(historian_push(points, sink, **opts))
