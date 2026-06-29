"""``iaiops modbus ...`` sub-commands (read-only Modbus-TCP)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.modbus import ops

modbus_app = typer.Typer(help="Modbus-TCP read-only telemetry (incl. 国产 PLCs).",
                         no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@modbus_app.command("holding")
@cli_errors
def holding_cmd(
    address: int,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
    decode: str = typer.Option("uint16", "--decode", help="raw|uint16|int16|uint32|int32|float32"),
) -> None:
    """Read holding registers (FC03)."""
    _emit(ops.modbus_read_holding(resolve_target(endpoint), address, count, decode))


@modbus_app.command("input")
@cli_errors
def input_cmd(
    address: int,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
    decode: str = typer.Option("uint16", "--decode"),
) -> None:
    """Read input registers (FC04)."""
    _emit(ops.modbus_read_input(resolve_target(endpoint), address, count, decode))


@modbus_app.command("coils")
@cli_errors
def coils_cmd(
    address: int,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read coils (FC01)."""
    _emit(ops.modbus_read_coils(resolve_target(endpoint), address, count))


@modbus_app.command("discrete")
@cli_errors
def discrete_cmd(
    address: int,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read discrete inputs (FC02)."""
    _emit(ops.modbus_read_discrete(resolve_target(endpoint), address, count))


@modbus_app.command("health")
@cli_errors
def health_cmd(
    endpoint: EndpointOption = None,
    address: list[int] = typer.Option(None, "--address", help="Register addresses (repeatable)"),
    register_type: str = typer.Option("holding", "--register-type", help="holding|input"),
) -> None:
    """Classify registers against warn/alarm thresholds (ok/warn/alarm counts)."""
    _emit(
        ops.modbus_health_summary(
            resolve_target(endpoint),
            list(address) if address else None,
            register_type=register_type,
        )
    )
