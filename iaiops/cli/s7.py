"""``iaiops s7 ...`` sub-commands (Siemens / 仿西门子 国产, read-first)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.s7 import ops

s7_app = typer.Typer(help="S7comm read-first telemetry (Siemens + 仿西门子).",
                     no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@s7_app.command("cpu")
@cli_errors
def cpu_cmd(endpoint: EndpointOption = None) -> None:
    """Show S7 CPU identity + run/stop status."""
    _emit(ops.s7_cpu_info(resolve_target(endpoint)))


@s7_app.command("read-db")
@cli_errors
def read_db_cmd(
    db: int,
    dtype: str,
    start: int,
    endpoint: EndpointOption = None,
    count: int = typer.Option(1, "--count"),
) -> None:
    """Read items from a data block (e.g. s7 read-db 1 REAL 4 --count 2)."""
    _emit(ops.s7_read_db(resolve_target(endpoint), db, dtype, start, count))


@s7_app.command("read")
@cli_errors
def read_cmd(
    addresses: list[str] = typer.Argument(..., help="pyS7 addresses, e.g. DB1,REAL4 M0.0"),
    endpoint: EndpointOption = None,
) -> None:
    """Batch-read raw pyS7 address strings."""
    _emit(ops.s7_read_many(resolve_target(endpoint), addresses))


@s7_app.command("write-db")
@cli_errors
def write_db_cmd(
    db: int,
    dtype: str,
    start: int,
    value: str,
    endpoint: EndpointOption = None,
    apply: bool = typer.Option(False, "--apply", help="Actually write (omit = dry-run)"),
) -> None:
    """[HIGH RISK] Write one value to a data block (dry-run unless --apply + confirm)."""
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.s7_write_db(target, db, dtype, start, value, dry_run=True))
        return
    console.print(
        f"[red]OT-DANGEROUS:[/] write DB{db}.{dtype}{start}={value} on "
        f"'{target.name}'. 未经授权勿对生产控制系统写入."
    )
    if not typer.confirm("Confirm you are authorized to write to this PLC?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — apply the write now?", default=False):
        raise typer.Abort()
    _emit(ops.s7_write_db(target, db, dtype, start, value, dry_run=False))
