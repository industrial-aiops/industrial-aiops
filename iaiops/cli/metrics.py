"""``iaiops metrics serve`` — Prometheus endpoint over the local SQLite sink.

Exposes ``/metrics`` (text format 0.0.4): latest tag values as gauges + internal
counters, straight from ``~/.iaiops/data.db`` and the audit log. Grafana recipe:
docs/GRAFANA.md.
"""

from __future__ import annotations

import typer
from rich.console import Console

from iaiops.cli._common import cli_errors
from iaiops.core.sink.prometheus import DEFAULT_HOST, DEFAULT_PORT, MetricsServer

metrics_app = typer.Typer(
    help="Prometheus/Grafana bridge over the local SQLite sink (read-only).",
    no_args_is_help=True,
)
console = Console()


@metrics_app.command("serve")
@cli_errors
def serve_cmd(
    port: int = typer.Option(DEFAULT_PORT, "--port", help="TCP port to listen on"),
    host: str = typer.Option(
        DEFAULT_HOST, "--host",
        help="Bind address (default 127.0.0.1; use 0.0.0.0 to expose — be sure)",
    ),
) -> None:
    """Serve /metrics for Prometheus from the local SQLite sink (data.db)."""
    if not 1 <= port <= 65535:
        raise ValueError(f"--port must be 1..65535 (got {port}).")
    if not (host or "").strip():
        raise ValueError("--host must not be empty.")
    if host == "0.0.0.0":  # nosec B104 — explicit operator choice, warned loudly
        console.print(
            "[yellow]WARNING: binding 0.0.0.0 exposes tag/endpoint names to "
            "every host that can reach this machine. Prefer 127.0.0.1, or "
            "firewall the port.[/]"
        )
    server = MetricsServer(host=host, port=port)
    console.print(
        f"Serving Prometheus metrics on http://{host}:{server.port}/metrics "
        f"(Ctrl-C to stop)."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("Stopped.")
    finally:
        server.stop()


__all__ = ["metrics_app"]
