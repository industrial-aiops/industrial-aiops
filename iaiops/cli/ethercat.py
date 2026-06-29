"""``iaiops ethercat ...`` sub-commands (EtherCAT fieldbus, read-first).

REAL pysoem/SOEM master. Requires Linux + root/CAP_NET_RAW + a dedicated NIC +
real slaves (optional extra: ``pip install iaiops[ethercat]``). No simulator;
macOS unsupported. Reads are non-destructive; SDO write and AL-state change are
OT-dangerous (dry-run unless ``--apply`` + double-confirm).
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.ethercat import ops

ethercat_app = typer.Typer(
    help="EtherCAT read-first telemetry (pysoem/SOEM; Linux+root+NIC+slaves).",
    no_args_is_help=True,
)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@ethercat_app.command("master")
@cli_errors
def master_cmd(endpoint: EndpointOption = None) -> None:
    """Show master/working-counter state and expected vs found slave count."""
    _emit(ops.ethercat_master_state(resolve_target(endpoint)))


@ethercat_app.command("slaves")
@cli_errors
def slaves_cmd(endpoint: EndpointOption = None) -> None:
    """Bus scan: enumerate slaves (id/vendor/product/rev/addr/state)."""
    _emit(ops.ethercat_slaves(resolve_target(endpoint)))


@ethercat_app.command("info")
@cli_errors
def info_cmd(slave: int, endpoint: EndpointOption = None) -> None:
    """Detail one slave: identity, SM/FMMU config, object-dictionary summary."""
    _emit(ops.ethercat_slave_info(resolve_target(endpoint), slave))


@ethercat_app.command("read-sdo")
@cli_errors
def read_sdo_cmd(
    slave: int,
    index: int,
    subindex: int = typer.Option(0, "--subindex"),
    size: int = typer.Option(0, "--size"),
    endpoint: EndpointOption = None,
) -> None:
    """CoE SDO upload: read one object-dictionary entry (e.g. read-sdo 0 4120)."""
    _emit(ops.ethercat_read_sdo(resolve_target(endpoint), slave, index, subindex, size))


@ethercat_app.command("read-pdo")
@cli_errors
def read_pdo_cmd(slave: int, endpoint: EndpointOption = None) -> None:
    """One cyclic snapshot of a slave's input process-data image."""
    _emit(ops.ethercat_read_pdo(resolve_target(endpoint), slave))


@ethercat_app.command("write-sdo")
@cli_errors
def write_sdo_cmd(
    slave: int,
    index: int,
    value: str,
    subindex: int = typer.Option(0, "--subindex"),
    endpoint: EndpointOption = None,
    apply: bool = typer.Option(False, "--apply", help="Actually write (omit = dry-run)"),
) -> None:
    """[HIGH RISK] CoE SDO download (dry-run unless --apply + confirm).

    VALUE is a hex string of the raw little-endian bytes (e.g. 'e803' = 1000 u16).
    """
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.ethercat_write_sdo(target, slave, index, value, subindex, dry_run=True))
        return
    console.print(
        f"[red]OT-DANGEROUS:[/] write SDO 0x{index:04X}:{subindex}=0x{value} on "
        f"slave {slave} of '{target.name}'. 未经授权勿对生产控制系统写入."
    )
    if not typer.confirm("Confirm you are authorized to write to this bus?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — apply the SDO write now?", default=False):
        raise typer.Abort()
    _emit(ops.ethercat_write_sdo(target, slave, index, value, subindex, dry_run=False))


@ethercat_app.command("set-state")
@cli_errors
def set_state_cmd(
    state: str,
    slave: int = typer.Option(-1, "--slave", help="Slave index, or -1 for the master"),
    endpoint: EndpointOption = None,
    apply: bool = typer.Option(False, "--apply", help="Actually transition (omit = dry-run)"),
) -> None:
    """[HIGH RISK] Request an AL-state transition (dry-run unless --apply + confirm).

    Changing EtherCAT state can START or STOP machine motion. STATE = INIT|PREOP|SAFEOP|OP.
    """
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.ethercat_set_state(target, state, slave, dry_run=True))
        return
    scope = "master" if slave < 0 else f"slave {slave}"
    console.print(
        f"[red]OT-DANGEROUS:[/] request state '{state}' on {scope} of '{target.name}'. "
        f"This can START or STOP machine motion. 未经授权勿对生产控制系统写入."
    )
    if not typer.confirm("Confirm you are authorized to change bus state?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — apply the state change now?", default=False):
        raise typer.Abort()
    _emit(ops.ethercat_set_state(target, state, slave, dry_run=False))
