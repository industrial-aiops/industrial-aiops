"""``iaiops iolink ...`` sub-commands (IO-Link master JSON, read-only)."""

from __future__ import annotations

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, resolve_target
from iaiops.connectors.iolink import ops

iolink_app = typer.Typer(
    help="IO-Link read-only sensor visibility via the master's JSON interface.",
    no_args_is_help=True,
)


@iolink_app.command("master")
@cli_errors
def master_cmd(endpoint: EndpointOption = None) -> None:
    """IO-Link master identity (/deviceinfo tree)."""
    _emit(ops.master_info(resolve_target(endpoint)))


@iolink_app.command("ports")
@cli_errors
def ports_cmd(
    endpoint: EndpointOption = None,
    count: int = typer.Option(ops.DEFAULT_PORT_COUNT, "--count", help="Ports to sweep (1..32)"),
) -> None:
    """Bounded port sweep: mode/status + connected device identity."""
    _emit(ops.ports(resolve_target(endpoint), count))


@iolink_app.command("device")
@cli_errors
def device_cmd(
    port: int = typer.Argument(..., help="Master port number (1..32)"),
    endpoint: EndpointOption = None,
) -> None:
    """Identity of the IO-Link device on one port."""
    _emit(ops.device_info(resolve_target(endpoint), port))


@iolink_app.command("pdin")
@cli_errors
def pdin_cmd(
    port: int = typer.Argument(..., help="Master port number (1..32)"),
    endpoint: EndpointOption = None,
) -> None:
    """Process-data-in of one port (raw hex + bytes)."""
    _emit(ops.read_pdin(resolve_target(endpoint), port))


@iolink_app.command("isdu")
@cli_errors
def isdu_cmd(
    port: int = typer.Argument(..., help="Master port number (1..32)"),
    index: int = typer.Argument(..., help="ISDU parameter index (0..65535)"),
    subindex: int = typer.Option(0, "--subindex", help="ISDU subindex (0..255)"),
    endpoint: EndpointOption = None,
) -> None:
    """ISDU acyclic parameter read (iolreadacyclic)."""
    _emit(ops.read_isdu(resolve_target(endpoint), port, index, subindex))


@iolink_app.command("scan")
@cli_errors
def scan_cmd(
    endpoint: EndpointOption = None,
    count: int = typer.Option(ops.DEFAULT_PORT_COUNT, "--count", help="Ports to sweep (1..32)"),
) -> None:
    """One-shot snapshot: master identity + every port's state."""
    _emit(ops.scan(resolve_target(endpoint), count))
