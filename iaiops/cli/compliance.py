"""``iaiops compliance`` / ``iaiops historian`` — 信创 / China-entry commands.

``compliance`` prints the 《工控系统网络安全防护指南》 ↔ iaiops mapping (an
onboarding/sales artifact); ``compliance report`` renders it into a deliverable
Markdown/HTML document and ``compliance evidence`` exports the audit-evidence
zip (A3). ``historian push`` writes collected telemetry (a JSON list of points)
to a domestic TSDB (TDengine / IoTDB) — 信创 data egress.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
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


compliance_app = typer.Typer(
    help="信创 / compliance: 防护指南 ↔ 等保 2.0 ↔ IEC 62443 mapping, rendered "
    "report, and audit-evidence bundle export.",
    invoke_without_command=True,
)


@compliance_app.callback()
@cli_errors
def compliance_cmd(
    ctx: typer.Context,
    frameworks: bool = typer.Option(
        False, "--frameworks", help="Print the 防护指南 ↔ 等保 2.0 ↔ IEC 62443 crosswalk instead."
    ),
    dengbao_level: str = typer.Option(
        "",
        "--dengbao-level",
        help="Print 等保 2.0 二级 vs 三级 per-pillar deltas (l2/l3, 二级/三级, 2/3; empty=both).",
    ),
) -> None:
    """Print the 《工控系统网络安全防护指南》 ↔ iaiops governance mapping.

    With --frameworks, print the cross-framework 对照 (等保 2.0 / IEC 62443) instead.
    With --dengbao-level, print the 等保 2.0 二级/三级 per-pillar deltas (pass a level
    to focus, or leave blank for both). Subcommands: report / evidence.
    """
    if ctx.invoked_subcommand is not None:
        return
    if dengbao_level:
        _emit(compliance_dengbao_levels(dengbao_level))
        return
    _emit(compliance_frameworks() if frameworks else compliance_mapping())


@compliance_app.command("report")
@cli_errors
def report_cmd(
    out: Path = typer.Option(..., "--out", help="Output file (e.g. report.md)."),
    html: bool = typer.Option(False, "--html", help="Render HTML instead of Markdown."),
    site: str = typer.Option("", "--site", help="Site / plant name for the title page."),
    level: str = typer.Option(
        "", "--level", help="等保 2.0 target level (l2/l3, 二级/三级); empty = both."
    ),
) -> None:
    """Render the 等保 2.0 / IEC 62443 compliance report (onboarding aid, 非认证)."""
    from iaiops.core.brain.compliance_report import (
        render_html_report,
        render_markdown_report,
    )
    from iaiops.core.governance.evidence import validate_output_path

    suffixes = (".html", ".htm") if html else (".md", ".markdown")
    path = validate_output_path(out, suffixes=suffixes)
    render = render_html_report if html else render_markdown_report
    content = render(
        site=site,
        date=datetime.now(tz=UTC).date().isoformat(),
        level=level or None,
    )
    path.write_text(content, encoding="utf-8")
    _emit(
        {
            "path": str(path),
            "format": "html" if html else "markdown",
            "lines": content.count("\n") + 1,
        }
    )


@compliance_app.command("evidence")
@cli_errors
def evidence_cmd(
    out: Path = typer.Option(..., "--out", help="Output zip (e.g. bundle.zip)."),
    since: str = typer.Option("", "--since", help="ISO-8601 floor on audit row ts."),
    until: str = typer.Option("", "--until", help="ISO-8601 ceiling on audit row ts."),
) -> None:
    """Export the audit-evidence bundle (audit rows + chain verify + rules + doctor)."""
    from iaiops.core.governance.evidence import export_evidence_bundle

    _emit(export_evidence_bundle(out, since=since or None, until=until or None))


historian_app = typer.Typer(
    help="信创 national-TSDB historian: push collected telemetry (TDengine/IoTDB/"
    "sqlite) and read it back (query/coverage — see iaiops/cli/historian.py).",
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
