"""MQTT / Sparkplug B / UNS MCP tools (consume-first).

Read/consume tools are governed at risk_level='low'. ``mqtt_publish`` is
risk_level='high' (MOC), off by default (dry_run). A published command has no
automatic inverse. 未经授权勿对生产控制系统下发指令.
"""

from typing import Any, Optional

from iaiops.connectors.sparkplug import live, ops
from iaiops.core.brain import uns_governance as uns
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sparkplug_decode_payload(
    payload: str, encoding: str = "base64", alias_map: Optional[dict[int, str]] = None
) -> dict:
    """[READ][risk=low] Decode a single raw Sparkplug B payload to structured metrics.

    Full protobuf decode (vendored Eclipse Tahu schema): per metric returns name,
    alias, datatype (Int/Float/Bool/String/DateTime/DataSet/Template…), value,
    timestamp, and is_historical / is_null flags. Rich types expand: a DataSet
    value decodes to {columns, types, rows} and a Template value to {template_ref,
    is_definition, version, members, parameters} (members decoded recursively).

    Args:
        payload: Raw Sparkplug B protobuf bytes as a string, ``base64`` (default) or ``hex``.
        encoding: 'base64' or 'hex'.
        alias_map: Optional {alias: name} (from a prior BIRTH) so alias-only
            NDATA/DDATA metrics resolve to names.

    Returns dict: {encoding:'sparkplug_b', timestamp, seq, uuid, metric_count,
        historical_count, metrics:[{name, alias, datatype, value, timestamp,
        is_historical, is_null}]}. A DataSet ``value`` is {dataset:true, columns,
        types, rows, row_count}; a Template ``value`` is {template:true,
        template_ref, is_definition, version, members:[{name, type, value}],
        parameters}.

    Example: sparkplug_decode_payload(payload="CAESBwoDYWJjEAE=", encoding="base64").
    """
    return ops.sparkplug_decode_payload(payload, encoding, alias_map)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mqtt_read_topic(
    endpoint: Optional[str] = None,
    topic: str = "",
    count: int = 25,
    timeout_s: int = 10,
) -> dict:
    """[READ][risk=low] Plain MQTT: collect a BOUNDED set of messages from a topic.

    Subscribes, gathers up to ``count`` messages or until ``timeout_s``, then
    disconnects — never an open-ended loop. Payloads are decoded as JSON/text;
    binary (e.g. Sparkplug protobuf) is reported with a hex preview + hint.

    Args:
        endpoint: Endpoint name from config (protocol must be 'mqtt').
        topic: Topic filter (default: the endpoint's configured topic or '#').
        count: Max messages (1..500, capped server-side).
        timeout_s: Max seconds to wait (1..60, capped server-side).

    Returns dict: {endpoint, topic, message_count, messages:[{topic,
        payload:{encoding, json|text|hex_preview}}]}.

    Example: mqtt_read_topic(topic="factory/+/temperature", count=10, timeout_s=5).
    """
    return ops.mqtt_read_topic(_target(endpoint), topic, count, timeout_s)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sparkplug_subscribe_sample(
    endpoint: Optional[str] = None,
    topic: str = "",
    count: int = 25,
    timeout_s: int = 10,
) -> dict:
    """[READ][risk=low] Bounded Sparkplug B sample with full decode + birth/death/seq.

    Topics are parsed and payloads fully protobuf-decoded; a birth/death + seq
    model resolves aliases (from NBIRTH/DBIRTH), applies NDATA/DDATA by alias, and
    flags is_historical metrics and seq gaps.

    Args:
        endpoint: Endpoint name from config.
        topic: Topic filter (default 'spBv1.0/#').
        count: Max messages (1..500).
        timeout_s: Max seconds to wait (1..60).

    Returns dict: {endpoint, topic, message_count, historical_metric_count,
        seq_gap_count, samples:[{topic, sparkplug:{group_id, message_type,
        edge_node_id, device_id}, payload:{metrics:[{name, alias, datatype, value,
        is_historical}]}}]}.

    Example: sparkplug_subscribe_sample(topic="spBv1.0/Plant1/#", count=20).
    """
    return ops.sparkplug_subscribe_sample(_target(endpoint), topic, count, timeout_s)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sparkplug_node_list(
    endpoint: Optional[str] = None, timeout_s: int = 10, count: int = 500
) -> dict:
    """[READ][risk=low] Discover edge nodes/devices + online state + primary-host STATE.

    Builds the birth/death + seq model from BIRTH/DATA/DEATH/STATE topics: each
    node reports online/born, its devices, learned metric aliases, and seq gaps;
    STATE topics surface primary-host status.

    Args:
        endpoint: Endpoint name from config.
        timeout_s: Observation window in seconds (1..60). Longer catches infrequent nodes.
        count: Max messages to inspect (1..500).

    Returns dict: {endpoint, node_count, nodes:[{group_id, edge_node_id, online,
        born, devices:[...], metric_aliases_known, seq_gap_count, seq_issues}],
        primary_hosts:[{host_id, state}]}.

    Example: sparkplug_node_list(timeout_s=15).
    """
    return ops.sparkplug_node_list(_target(endpoint), timeout_s, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def uns_browse(
    endpoint: Optional[str] = None, topic: str = "#", timeout_s: int = 10, count: int = 500
) -> dict:
    """[READ][risk=low] Browse the live topic tree (UNS) under a filter (bounded).

    Args:
        endpoint: Endpoint name from config.
        topic: Topic filter to browse under (default '#').
        timeout_s: Observation window in seconds (1..60).
        count: Max messages to inspect (1..500).

    Returns dict: {endpoint, filter, topic_count, topics:[...], tree:{nested segments}}.

    Example: uns_browse(topic="factory/#", timeout_s=8).
    """
    return ops.uns_browse(_target(endpoint), topic, timeout_s, count)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def mqtt_publish(
    topic: str,
    payload: str,
    endpoint: Optional[str] = None,
    qos: int = 0,
    retain: bool = False,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Publish/command to an MQTT topic (off by default).

    OT-DANGEROUS. A command (e.g. Sparkplug NCMD/DCMD) can change a live control
    system and has NO automatic inverse. Defaults to dry_run=True. Set
    dry_run=False AND record an approver (OPCUA_AUDIT_APPROVED_BY) to send.
    未经授权勿对生产控制系统下发指令.

    Args:
        topic: MQTT topic to publish to.
        payload: Message payload (string; JSON is fine).
        endpoint: Endpoint name from config.
        qos: MQTT QoS 0..2.
        retain: Set the broker retain flag.
        dry_run: When True (default) returns a preview without publishing.

    Returns dict: dry-run → {topic, dry_run:true, would_publish_bytes, note};
        applied → {topic, dry_run:false, published_bytes, applied:true}.

    Example (preview): mqtt_publish(topic="factory/line1/cmd", payload='{"setpoint":50}').
    """
    return ops.mqtt_publish(
        _target(endpoint), topic, payload, qos=qos, retain=retain, dry_run=dry_run
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def uns_topic_audit(
    topics: list[str],
    allowed_roots: Optional[list[str]] = None,
    min_segments: int = 0,
    max_leaf_parents: int = 5,
) -> dict:
    """[READ][risk=low] Govern a UNS topic tree: naming conformance + topic sprawl.

    Pure analysis over a provided list of UNS topic strings (no live broker). Flags
    non-conforming roots, too-shallow topics, casing collisions of the same logical
    name, leaf metrics scattered under many parents, depth outliers, and duplicates.

    Args:
        topics: UNS topic strings, e.g. ["Enterprise/Site/Area/Line1/temperature", ...].
        allowed_roots: Permitted top-level segments; others are flagged (optional).
        min_segments: Minimum namespace depth a well-formed topic must have.
        max_leaf_parents: A leaf appearing under more than this many parents is scattered.

    Returns dict: {topic_count, unique_topics, root_count, roots[], depth{min,max,mean},
        verdict ('clean'|'minor'|'sprawling'), sprawl_findings, findings{
        non_conforming_root[], too_shallow[], casing_collisions[], scattered_leaves[],
        depth_outliers[], duplicate_topics[]}}.

    Example: uns_topic_audit(topics=["Ent/Site/Line1/temp","Ent/site/Line1/Temp"],
        allowed_roots=["Ent"], min_segments=3).
    """
    return uns.uns_topic_audit(topics, allowed_roots, min_segments, max_leaf_parents)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def uns_schema_drift(baseline: dict[str, Any], current: dict[str, Any]) -> dict:
    """[READ][risk=low] Detect Sparkplug/UNS schema drift between two snapshots.

    Compares baseline vs current node/metric definitions (e.g. two NBIRTH snapshots)
    and reports added / removed / type-changed metrics per node, with a verdict.

    Args:
        baseline: {node: {metric: datatype}} or [{node|topic, metrics:[{name, datatype}]}].
        current: Same shape — the newer snapshot to compare against the baseline.

    Returns dict: {baseline_nodes, current_nodes, changed_nodes,
        verdict ('none'|'additive'|'breaking'), node_changes:[{node, node_status,
        added[], removed[], type_changed:[{metric, from, to}]}]}.

    Example: uns_schema_drift(baseline={"N1":{"temp":"Float"}},
        current={"N1":{"temp":"Int32","rpm":"Float"}}).
    """
    return uns.uns_schema_drift(baseline, current)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def uns_live_audit(
    endpoint: Optional[str] = None,
    topic: str = "#",
    duration_s: int = 10,
    max_msgs: int = 500,
    allowed_roots: Optional[list[str]] = None,
    min_segments: int = 0,
    max_leaf_parents: int = 5,
) -> dict:
    """[READ][risk=low] Capture the LIVE UNS topic tree (bounded) then audit it.

    Closes the governance loop: subscribes to a live broker, collects up to
    ``max_msgs`` messages or until ``duration_s`` (whichever first), then runs the
    naming-conformance + topic-sprawl audit over the observed topics. Never an
    open-ended loop.

    Args:
        endpoint: Endpoint name from config (protocol must be 'mqtt').
        topic: Topic filter to capture under (default '#').
        duration_s: Capture window in seconds (1..60, capped server-side).
        max_msgs: Max messages to capture (1..500, capped server-side).
        allowed_roots: Permitted top-level segments; others are flagged (optional).
        min_segments: Minimum namespace depth a well-formed topic must have.
        max_leaf_parents: A leaf under more than this many parents is scattered.

    Returns dict: the uns_topic_audit result (topic_count, depth, verdict, findings)
        plus capture:{endpoint, topic, observed_messages, unique_topics, topics[]}.

    Example: uns_live_audit(topic="factory/#", duration_s=8, allowed_roots=["factory"]).
    """
    return live.uns_live_audit(
        _target(endpoint),
        topic,
        duration_s,
        max_msgs,
        allowed_roots,
        min_segments,
        max_leaf_parents,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sparkplug_live_schema(
    endpoint: Optional[str] = None,
    topic: str = "spBv1.0/#",
    duration_s: int = 10,
    max_msgs: int = 500,
) -> dict:
    """[READ][risk=low] Capture a LIVE Sparkplug schema (bounded) → drift-ready dict.

    Subscribes, collects up to ``max_msgs`` messages or until ``duration_s``, decodes
    NBIRTH/DBIRTH metrics, and returns ``schema`` = {node: {metric: datatype}} (node =
    group/edge[/device]) — exactly the shape uns_schema_drift accepts. Use it as a
    baseline or current snapshot.

    Args:
        endpoint: Endpoint name from config.
        topic: Topic filter (default 'spBv1.0/#').
        duration_s: Capture window in seconds (1..60).
        max_msgs: Max messages to capture (1..500).

    Returns dict: {endpoint, topic, message_count, birth_count, node_count,
        schema:{node:{metric:datatype}}}.

    Example: sparkplug_live_schema(topic="spBv1.0/Plant1/#", duration_s=15).
    """
    return live.sparkplug_live_schema(_target(endpoint), topic, duration_s, max_msgs)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def uns_live_drift(
    baseline: dict[str, Any],
    endpoint: Optional[str] = None,
    topic: str = "spBv1.0/#",
    duration_s: int = 10,
    max_msgs: int = 500,
) -> dict:
    """[READ][risk=low] Capture the LIVE Sparkplug schema (bounded) and diff vs baseline.

    Captures current node/metric definitions from live BIRTHs, then runs schema drift
    against ``baseline`` — added / removed / type-changed metrics per node with a
    none/additive/breaking verdict.

    Args:
        baseline: Prior schema {node:{metric:datatype}} (e.g. from sparkplug_live_schema).
        endpoint: Endpoint name from config.
        topic: Topic filter (default 'spBv1.0/#').
        duration_s: Capture window in seconds (1..60).
        max_msgs: Max messages to capture (1..500).

    Returns dict: the uns_schema_drift result (changed_nodes, verdict, node_changes)
        plus capture:{endpoint, topic, message_count, birth_count, node_count}.

    Example: uns_live_drift(baseline={"Plant1/Edge1":{"Temperature":"Double"}}).
    """
    return live.uns_live_drift(_target(endpoint), baseline, topic, duration_s, max_msgs)
