"""``iaiops fins ...`` sub-commands (Omron CS/CJ/CP/NX-via-FINS, read-first)."""

from __future__ import annotations

import typer

from iaiops.cli._common import (
    EndpointOption,
    _emit,
    cli_errors,
    console,
    high_risk,
    resolve_target,
)
from iaiops.connectors.fins import ops

fins_app = typer.Typer(
    help="Omron FINS read-first telemetry (CS/CJ/CP/NX-via-FINS).", no_args_is_help=True
)


@fins_app.command("cpu")
@cli_errors
def cpu_cmd(endpoint: EndpointOption = None) -> None:
    """Show Omron CPU model/version via FINS 0501 (proves the FINS link)."""
    _emit(ops.fins_cpu_info(resolve_target(endpoint)))


@fins_app.command("status")
@cli_errors
def status_cmd(endpoint: EndpointOption = None) -> None:
    """Show controller run/stop status + mode + error flags (FINS 0601)."""
    _emit(ops.fins_cpu_status(resolve_target(endpoint)))


@fins_app.command("words")
@cli_errors
def words_cmd(
    address: int,
    endpoint: EndpointOption = None,
    area: str = typer.Option("DM", "--area", help="DM|CIO|W|H|A|EM"),
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read words (e.g. fins words 100 --area DM --count 8)."""
    _emit(ops.fins_read_words(resolve_target(endpoint), area, address, count))


@fins_app.command("bits")
@cli_errors
def bits_cmd(
    address: int,
    endpoint: EndpointOption = None,
    area: str = typer.Option("CIO", "--area", help="CIO|W|H|A|DM"),
    bit: int = typer.Option(0, "--bit", help="Bit within the word (0..15)"),
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read bits (e.g. fins bits 0 --area CIO --bit 0 --count 16)."""
    _emit(ops.fins_read_bits(resolve_target(endpoint), area, address, bit, count))


@fins_app.command("write-words")
@high_risk
@cli_errors
def write_words_cmd(
    address: int,
    values: list[int] = typer.Argument(..., help="Word values to write"),
    endpoint: EndpointOption = None,
    area: str = typer.Option("DM", "--area", help="DM|CIO|W|H|A|EM"),
    apply: bool = typer.Option(False, "--apply", help="Actually write (omit = dry-run)"),
) -> None:
    """[HIGH RISK] Write words to an area (dry-run unless --apply + confirm)."""
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.fins_write_words(target, area, address, values, dry_run=True))
        return
    console.print(
        f"[red]OT-DANGEROUS:[/] write {area}{address}={values} on '{target.name}'. "
        f"未经授权勿对生产控制系统写入."
    )
    if not typer.confirm("Confirm you are authorized to write to this PLC?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — apply the write now?", default=False):
        raise typer.Abort()
    _emit(ops.fins_write_words(target, area, address, values, dry_run=False))
