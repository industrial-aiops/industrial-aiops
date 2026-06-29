"""``iaiops eip ...`` sub-commands (EtherNet/IP — Rockwell/AB Logix, read-first)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.eip import ops

eip_app = typer.Typer(help="EtherNet/IP read-first telemetry (Allen-Bradley Logix).",
                      no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@eip_app.command("info")
@cli_errors
def info_cmd(endpoint: EndpointOption = None) -> None:
    """Show Logix controller identity (name/product/revision/serial)."""
    _emit(ops.eip_controller_info(resolve_target(endpoint)))


@eip_app.command("tags")
@cli_errors
def tags_cmd(endpoint: EndpointOption = None) -> None:
    """Discover the controller's tag list (names/types/structures)."""
    _emit(ops.eip_list_tags(resolve_target(endpoint)))


@eip_app.command("read")
@cli_errors
def read_cmd(tag: str, endpoint: EndpointOption = None) -> None:
    """Read one Logix tag (or array element)."""
    _emit(ops.eip_read_tag(resolve_target(endpoint), tag))


@eip_app.command("read-many")
@cli_errors
def read_many_cmd(
    tags: list[str] = typer.Argument(..., help="Logix tag names to batch-read"),
    endpoint: EndpointOption = None,
) -> None:
    """Batch-read many Logix tags in one request."""
    _emit(ops.eip_read_many(resolve_target(endpoint), tags))


@eip_app.command("write-tag")
@cli_errors
def write_tag_cmd(
    tag: str,
    value: str,
    endpoint: EndpointOption = None,
    apply: bool = typer.Option(False, "--apply", help="Actually write (omit = dry-run)"),
) -> None:
    """[HIGH RISK] Write one value to a Logix tag (dry-run unless --apply + confirm)."""
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.eip_write_tag(target, tag, value, dry_run=True))
        return
    console.print(
        f"[red]OT-DANGEROUS:[/] write tag '{tag}'={value} on '{target.name}'. "
        f"未经授权勿对生产控制系统写入."
    )
    if not typer.confirm("Confirm you are authorized to write to this PLC?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — apply the write now?", default=False):
        raise typer.Abort()
    _emit(ops.eip_write_tag(target, tag, value, dry_run=False))
