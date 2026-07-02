"""``iaiops audit`` — read-only egress of the governance audit log.

``audit forward`` streams new audit rows (as JSON lines) to a syslog (UDP) or
HTTP POST collector, with a persisted since-cursor so re-runs never duplicate.
"""

from __future__ import annotations

import json

import typer

from iaiops.cli._common import cli_errors, console
from iaiops.core.governance.forward import build_sink, forward_audit, forward_follow

audit_app = typer.Typer(
    name="audit",
    help="Forward the audit log to an external SIEM (read-only egress).",
    no_args_is_help=True,
)


@audit_app.command("forward")
@cli_errors
def audit_forward(
    sink: str = typer.Option(..., "--sink", help="syslog | http"),
    host: str = typer.Option(..., "--host", help="Collector host (or base URL for http)"),
    port: int = typer.Option(0, "--port", help="Port (default 514 syslog / 80|443 http)"),
    path: str = typer.Option("/", "--path", help="HTTP POST path (http sink only)"),
    since: str = typer.Option(
        "", "--since", help="Only forward rows with ts >= this ISO timestamp (first run)"
    ),
    follow: bool = typer.Option(False, "--follow", help="Keep polling and forwarding new rows"),
    interval: float = typer.Option(5.0, "--interval", help="Poll seconds when --follow"),
) -> None:
    """Forward new audit-log rows to a SIEM as JSON lines (read-only egress)."""
    dest = build_sink(sink, host=host, port=port, path=path)
    try:
        if follow:
            result = forward_follow(dest, since=since or None, interval=interval)
        else:
            result = forward_audit(dest, since=since or None)
    finally:
        dest.close()
    console.print_json(json.dumps(result, default=str))
