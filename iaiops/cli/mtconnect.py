"""``iaiops mtconnect ...`` sub-commands (CNC machine tools, read-only)."""

from __future__ import annotations

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, resolve_target
from iaiops.connectors.mtconnect import ops

mtconnect_app = typer.Typer(help="MTConnect read-only CNC telemetry.", no_args_is_help=True)


@mtconnect_app.command("probe")
@cli_errors
def probe_cmd(endpoint: EndpointOption = None) -> None:
    """Show the device model (components + data items)."""
    _emit(ops.mtconnect_probe(resolve_target(endpoint)))


@mtconnect_app.command("current")
@cli_errors
def current_cmd(endpoint: EndpointOption = None) -> None:
    """Latest value of every data item."""
    _emit(ops.mtconnect_current(resolve_target(endpoint)))


@mtconnect_app.command("sample")
@cli_errors
def sample_cmd(
    endpoint: EndpointOption = None,
    count: int = typer.Option(100, "--count"),
) -> None:
    """A bounded stream of recent observations."""
    _emit(ops.mtconnect_sample(resolve_target(endpoint), count))


@mtconnect_app.command("assets")
@cli_errors
def assets_cmd(endpoint: EndpointOption = None) -> None:
    """Assets (cutting tools, fixtures, programs)."""
    _emit(ops.mtconnect_assets(resolve_target(endpoint)))


@mtconnect_app.command("oee")
@cli_errors
def oee_cmd(endpoint: EndpointOption = None) -> None:
    """Availability / Execution / mode / program (OEE inputs)."""
    _emit(ops.mtconnect_oee_snapshot(resolve_target(endpoint)))
