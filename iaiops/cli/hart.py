"""``iaiops hart ...`` sub-commands (read-only HART-IP process instrumentation)."""

from __future__ import annotations

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, resolve_target
from iaiops.connectors.hart import ops

hart_app = typer.Typer(help="HART-IP read-only process-instrumentation telemetry.",
                       no_args_is_help=True)


@hart_app.command("identity")
@cli_errors
def identity_cmd(endpoint: EndpointOption = None) -> None:
    """Read the HART universal device identity (command 0)."""
    _emit(ops.hart_device_identity(resolve_target(endpoint)))


@hart_app.command("pv")
@cli_errors
def pv_cmd(endpoint: EndpointOption = None) -> None:
    """Read the HART primary variable (command 1)."""
    _emit(ops.hart_primary_variable(resolve_target(endpoint)))


@hart_app.command("dynamic")
@cli_errors
def dynamic_cmd(endpoint: EndpointOption = None) -> None:
    """Read the HART dynamic variables + loop current (command 3)."""
    _emit(ops.hart_dynamic_variables(resolve_target(endpoint)))
