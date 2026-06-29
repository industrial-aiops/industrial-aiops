"""``iaiops opcua ...`` sub-commands (read-only OPC-UA + problem surfacing)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.opcua import ops
from iaiops.core.brain import analysis
from iaiops.core.brain import monitor as mon

opcua_app = typer.Typer(help="OPC-UA read-only telemetry & problem surfacing.",
                        no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@opcua_app.command("info")
@cli_errors
def info_cmd(endpoint: EndpointOption = None) -> None:
    """Show OPC-UA server status, build info, and namespaces."""
    _emit(ops.server_info(resolve_target(endpoint)))


@opcua_app.command("browse")
@cli_errors
def browse_cmd(
    node_id: str = typer.Argument("i=85", help="Root node id to browse from"),
    endpoint: EndpointOption = None,
    depth: int = typer.Option(2, "--depth", help="Bounded browse depth"),
) -> None:
    """Browse the node tree from a node id (bounded depth)."""
    _emit(ops.browse(resolve_target(endpoint), node_id, depth))


@opcua_app.command("read")
@cli_errors
def read_cmd(node_id: str, endpoint: EndpointOption = None) -> None:
    """Read one node (value, datatype, timestamp, status code)."""
    _emit(ops.read_node(resolve_target(endpoint), node_id))


@opcua_app.command("read-many")
@cli_errors
def read_many_cmd(
    node_ids: list[str] = typer.Argument(..., help="Node ids to batch-read"),
    endpoint: EndpointOption = None,
) -> None:
    """Batch-read multiple node ids."""
    _emit(ops.read_many(resolve_target(endpoint), node_ids))


@opcua_app.command("sample")
@cli_errors
def sample_cmd(
    node_id: str,
    endpoint: EndpointOption = None,
    samples: int = typer.Option(5, "--samples"),
    interval_ms: int = typer.Option(500, "--interval-ms"),
    timeout_s: int = typer.Option(30, "--timeout-s"),
) -> None:
    """Sample a node a bounded number of times, then return."""
    _emit(ops.subscribe_sample(resolve_target(endpoint), node_id, samples, interval_ms, timeout_s))


@opcua_app.command("alarms")
@cli_errors
def alarms_cmd(
    endpoint: EndpointOption = None,
    node_id: str = typer.Option("i=85", "--node-id"),
    depth: int = typer.Option(4, "--depth"),
) -> None:
    """Surface active alarm-like conditions (best-effort)."""
    _emit(ops.read_alarms(resolve_target(endpoint), node_id, depth))


@opcua_app.command("health")
@cli_errors
def health_cmd(
    endpoint: EndpointOption = None,
    node_id: list[str] = typer.Option(None, "--node-id", help="Tag node ids (repeatable)"),
) -> None:
    """Classify tags against warn/alarm thresholds (ok/warn/alarm counts)."""
    _emit(analysis.health_summary(resolve_target(endpoint), list(node_id) if node_id else None))


@opcua_app.command("history")
@cli_errors
def history_cmd(
    node_id: str,
    endpoint: EndpointOption = None,
    start: str = typer.Option(None, "--start", help="ISO-8601 window start"),
    end: str = typer.Option(None, "--end", help="ISO-8601 window end"),
    max_points: int = typer.Option(1000, "--max-points"),
) -> None:
    """Read OPC-UA Historical Access (HDA) raw values over a window."""
    _emit(ops.read_history(resolve_target(endpoint), node_id, start, end, max_points))


@opcua_app.command("monitor")
@cli_errors
def monitor_cmd(
    node_id: str,
    endpoint: EndpointOption = None,
    duration_s: int = typer.Option(10, "--duration-s"),
    interval_ms: int = typer.Option(500, "--interval-ms"),
    deadband: float = typer.Option(0.0, "--deadband"),
    max_changes: int = typer.Option(100, "--max-changes"),
) -> None:
    """Bounded change-of-value capture (only changes, never an open loop)."""
    _emit(mon.monitor_changes(
        resolve_target(endpoint), node_id, duration_s, interval_ms, deadband, max_changes))


@opcua_app.command("anomaly")
@cli_errors
def anomaly_cmd(
    node_id: str,
    endpoint: EndpointOption = None,
    samples: int = typer.Option(20, "--samples"),
    interval_ms: int = typer.Option(200, "--interval-ms"),
    sigma: float = typer.Option(3.0, "--sigma"),
) -> None:
    """Sample a node and flag statistical outliers (mean ± sigma*stddev)."""
    _emit(analysis.anomaly_scan(resolve_target(endpoint), node_id, samples, interval_ms, sigma))
