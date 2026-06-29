"""``iaiops mc ...`` sub-commands (Mitsubishi Q/L/iQ-R, read-first)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.mc import ops

mc_app = typer.Typer(help="Mitsubishi MC read-first telemetry (Q/L/iQ-R).",
                     no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@mc_app.command("cpu")
@cli_errors
def cpu_cmd(endpoint: EndpointOption = None) -> None:
    """Show MELSEC CPU type/code (proves the MC link)."""
    _emit(ops.mc_cpu_status(resolve_target(endpoint)))


@mc_app.command("words")
@cli_errors
def words_cmd(
    headdevice: str,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read word devices (e.g. mc words D100 --count 8)."""
    _emit(ops.mc_read_words(resolve_target(endpoint), headdevice, count))


@mc_app.command("bits")
@cli_errors
def bits_cmd(
    headdevice: str,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read bit devices (e.g. mc bits M0 --count 16)."""
    _emit(ops.mc_read_bits(resolve_target(endpoint), headdevice, count))


@mc_app.command("write-words")
@cli_errors
def write_words_cmd(
    headdevice: str,
    values: list[int] = typer.Argument(..., help="Word values to write"),
    endpoint: EndpointOption = None,
    apply: bool = typer.Option(False, "--apply", help="Actually write (omit = dry-run)"),
) -> None:
    """[HIGH RISK] Write words from a head device (dry-run unless --apply + confirm)."""
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.mc_write_words(target, headdevice, values, dry_run=True))
        return
    console.print(
        f"[red]OT-DANGEROUS:[/] write {headdevice}={values} on '{target.name}'. "
        f"未经授权勿对生产控制系统写入."
    )
    if not typer.confirm("Confirm you are authorized to write to this PLC?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — apply the write now?", default=False):
        raise typer.Abort()
    _emit(ops.mc_write_words(target, headdevice, values, dry_run=False))
