"""``iaiops mqtt ...`` sub-commands (MQTT / Sparkplug B / UNS, consume-first)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.sparkplug import ops

mqtt_app = typer.Typer(help="MQTT / Sparkplug B / UNS consume-first telemetry.",
                       no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@mqtt_app.command("read")
@cli_errors
def read_cmd(
    endpoint: EndpointOption = None,
    topic: str = typer.Option("", "--topic"),
    count: int = typer.Option(25, "--count"),
    timeout_s: int = typer.Option(10, "--timeout-s"),
) -> None:
    """Collect a bounded set of plain MQTT messages from a topic filter."""
    _emit(ops.mqtt_read_topic(resolve_target(endpoint), topic, count, timeout_s))


@mqtt_app.command("nodes")
@cli_errors
def nodes_cmd(
    endpoint: EndpointOption = None,
    timeout_s: int = typer.Option(10, "--timeout-s"),
) -> None:
    """Discover Sparkplug edge nodes/devices from BIRTH topics."""
    _emit(ops.sparkplug_node_list(resolve_target(endpoint), timeout_s))


@mqtt_app.command("browse")
@cli_errors
def browse_cmd(
    endpoint: EndpointOption = None,
    topic: str = typer.Option("#", "--topic"),
    timeout_s: int = typer.Option(10, "--timeout-s"),
) -> None:
    """Browse the live topic tree (UNS) under a filter."""
    _emit(ops.uns_browse(resolve_target(endpoint), topic, timeout_s))


@mqtt_app.command("publish")
@cli_errors
def publish_cmd(
    topic: str,
    payload: str,
    endpoint: EndpointOption = None,
    qos: int = typer.Option(0, "--qos"),
    retain: bool = typer.Option(False, "--retain"),
    apply: bool = typer.Option(False, "--apply", help="Actually publish (omit = dry-run)"),
) -> None:
    """[HIGH RISK] Publish/command to a topic (dry-run unless --apply + confirm)."""
    target = resolve_target(endpoint)
    if not apply:
        _emit(ops.mqtt_publish(target, topic, payload, qos=qos, retain=retain, dry_run=True))
        return
    console.print(
        f"[red]OT-DANGEROUS:[/] publish to '{topic}' on '{target.name}'. A command "
        f"cannot be auto-undone. 未经授权勿对生产控制系统下发指令."
    )
    if not typer.confirm("Confirm you are authorized to command this system?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — publish now?", default=False):
        raise typer.Abort()
    _emit(ops.mqtt_publish(target, topic, payload, qos=qos, retain=retain, dry_run=False))
