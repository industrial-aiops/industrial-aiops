"""``iaiops iec104 ...`` sub-commands (IEC 60870-5-104, read-only monitoring).

c104 optional extra: ``pip install iaiops[iec104]``. Monitor direction only —
no control commands. Preview: not verified against a live RTU.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.iec104 import ops

iec104_app = typer.Typer(help="IEC 60870-5-104 read-only telemetry (c104).",
                         no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@iec104_app.command("info")
@cli_errors
def info_cmd(endpoint: EndpointOption = None) -> None:
    """Connect and show link status + discovered stations (ASDU CAs)."""
    _emit(ops.iec104_connection_info(resolve_target(endpoint)))


@iec104_app.command("interrogate")
@cli_errors
def interrogate_cmd(
    common_address: int = typer.Option(None, "--ca", help="ASDU common address"),
    endpoint: EndpointOption = None,
) -> None:
    """General interrogation: all monitored points of a station."""
    _emit(ops.iec104_interrogate(resolve_target(endpoint), common_address))


@iec104_app.command("read")
@cli_errors
def read_cmd(
    io_address: int,
    common_address: int = typer.Option(None, "--ca", help="ASDU common address"),
    endpoint: EndpointOption = None,
) -> None:
    """Read one monitored point by information-object address (IOA)."""
    _emit(ops.iec104_read_point(resolve_target(endpoint), io_address, common_address))
