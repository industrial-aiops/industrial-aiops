"""``iaiops modbus ...`` sub-commands (read-only Modbus-TCP)."""

from __future__ import annotations

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, resolve_target
from iaiops.connectors.modbus import ops

modbus_app = typer.Typer(
    help="Modbus-TCP read-only telemetry (incl. 国产 PLCs).", no_args_is_help=True
)


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


@modbus_app.command("templates")
@cli_errors
def templates_cmd() -> None:
    """List the built-in register-map templates. Contacts nothing.

    Modbus has no symbol table on the wire, so "what points does this device
    have" cannot be asked of the device. What the product does have is a set of
    vendor register maps — and until now they were reachable only from the MCP
    side, so a CLI user was told to type addresses in by hand while the answer
    for their meter was already in the box.

    A template is a starting point, not a fact about your device: check the
    `caveat` column and the vendor document before you trust the mapping.
    """
    _emit(ops.modbus_list_templates())


@modbus_app.command("template")
@cli_errors
def template_cmd(
    name: str,
    endpoint: EndpointOption = None,
    address: int = typer.Option(None, "--address", help="Override the template's base offset."),
    count: int = typer.Option(None, "--count", help="Override the template's register span."),
) -> None:
    """Read a register block through a template and show the decoded, named tags.

    This READS the device — one block of the register file the template names.
    Compare the decoded values against what the equipment actually reads out
    before you copy the addresses into `tags:`; a template that decodes into
    plausible-looking numbers on the wrong device is exactly the failure the
    empty `role` column exists to prevent.
    """
    _emit(ops.modbus_apply_template(resolve_target(endpoint), name, address, count))
