"""``iaiops iec61850 ...`` sub-commands (IEC 61850 MMS, read-only).

libiec61850 optional extra: ``pip install iaiops[iec61850]`` (needs libiec61850
built). Browse + read only — no control blocks. Preview: not verified against a
live IED.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.iec61850 import ops

iec61850_app = typer.Typer(help="IEC 61850 MMS read-only browse/read (libiec61850).",
                           no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@iec61850_app.command("directory")
@cli_errors
def directory_cmd(
    children: bool = typer.Option(False, "--children", help="Also browse one level of children"),
    endpoint: EndpointOption = None,
) -> None:
    """List the IED's logical devices (optionally their immediate children)."""
    _emit(ops.iec61850_device_directory(resolve_target(endpoint), children))


@iec61850_app.command("browse")
@cli_errors
def browse_cmd(reference: str, endpoint: EndpointOption = None) -> None:
    """Browse immediate model children under a reference (LD/LN/DO)."""
    _emit(ops.iec61850_browse(resolve_target(endpoint), reference))


@iec61850_app.command("read")
@cli_errors
def read_cmd(
    reference: str,
    fc: str = typer.Option("MX", "--fc", help="Functional constraint (MX/ST/CF/…)"),
    endpoint: EndpointOption = None,
) -> None:
    """Read one data attribute by object-reference + functional constraint."""
    _emit(ops.iec61850_read(resolve_target(endpoint), reference, fc))
