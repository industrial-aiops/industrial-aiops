"""``iaiops mqtt ...`` sub-commands (MQTT / Sparkplug B / UNS, consume-first)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, console, resolve_target
from iaiops.connectors.sparkplug import live, ops
from iaiops.core.brain import uns_governance as uns

mqtt_app = typer.Typer(
    help="MQTT / Sparkplug B / UNS consume-first telemetry.", no_args_is_help=True
)


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


@mqtt_app.command("uns-audit")
@cli_errors
def uns_audit_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of UNS topic strings"),
    root: list[str] = typer.Option(None, "--root", help="Allowed top-level root (repeatable)"),
    min_segments: int = typer.Option(0, "--min-segments"),
    max_leaf_parents: int = typer.Option(5, "--max-leaf-parents"),
) -> None:
    """Govern a UNS topic tree: naming conformance + topic sprawl (over a JSON list)."""
    topics = json.loads(Path(input).read_text("utf-8"))
    _emit(uns.uns_topic_audit(topics, list(root) if root else None, min_segments, max_leaf_parents))


@mqtt_app.command("uns-drift")
@cli_errors
def uns_drift_cmd(
    baseline: Path = typer.Option(..., "--baseline", help="JSON: baseline node/metric schema"),
    current: Path = typer.Option(..., "--current", help="JSON: current node/metric schema"),
) -> None:
    """Detect Sparkplug/UNS schema drift between two snapshot JSON files."""
    base = json.loads(Path(baseline).read_text("utf-8"))
    curr = json.loads(Path(current).read_text("utf-8"))
    _emit(uns.uns_schema_drift(base, curr))


@mqtt_app.command("uns-live-audit")
@cli_errors
def uns_live_audit_cmd(
    endpoint: EndpointOption = None,
    topic: str = typer.Option("#", "--topic"),
    duration_s: int = typer.Option(10, "--duration-s"),
    max_msgs: int = typer.Option(500, "--max-msgs"),
    root: list[str] = typer.Option(None, "--root", help="Allowed top-level root (repeatable)"),
    min_segments: int = typer.Option(0, "--min-segments"),
    max_leaf_parents: int = typer.Option(5, "--max-leaf-parents"),
) -> None:
    """Capture the LIVE UNS topic tree (bounded) then audit naming + sprawl."""
    _emit(
        live.uns_live_audit(
            resolve_target(endpoint),
            topic,
            duration_s,
            max_msgs,
            list(root) if root else None,
            min_segments,
            max_leaf_parents,
        )
    )


@mqtt_app.command("live-schema")
@cli_errors
def live_schema_cmd(
    endpoint: EndpointOption = None,
    topic: str = typer.Option("spBv1.0/#", "--topic"),
    duration_s: int = typer.Option(10, "--duration-s"),
    max_msgs: int = typer.Option(500, "--max-msgs"),
) -> None:
    """Capture a LIVE Sparkplug schema (bounded) → drift-ready {node:{metric:type}}."""
    _emit(live.sparkplug_live_schema(resolve_target(endpoint), topic, duration_s, max_msgs))


@mqtt_app.command("uns-live-drift")
@cli_errors
def uns_live_drift_cmd(
    baseline: Path = typer.Option(..., "--baseline", help="JSON: baseline node/metric schema"),
    endpoint: EndpointOption = None,
    topic: str = typer.Option("spBv1.0/#", "--topic"),
    duration_s: int = typer.Option(10, "--duration-s"),
    max_msgs: int = typer.Option(500, "--max-msgs"),
) -> None:
    """Capture the LIVE Sparkplug schema (bounded) and diff it vs a baseline JSON."""
    base = json.loads(Path(baseline).read_text("utf-8"))
    _emit(live.uns_live_drift(resolve_target(endpoint), base, topic, duration_s, max_msgs))
