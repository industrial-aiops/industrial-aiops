"""MQTT / Sparkplug B / UNS MCP tools (consume-first).

Read/consume tools are governed at risk_level='low'. ``mqtt_publish`` is
risk_level='high' (MOC), off by default (dry_run). A published command has no
automatic inverse. 未经授权勿对生产控制系统下发指令.
"""

from typing import Optional

from iaiops.connectors.sparkplug import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sparkplug_decode_payload(
    payload: str, encoding: str = "base64", alias_map: Optional[dict] = None
) -> dict:
    """[READ][risk=low] Decode a single raw Sparkplug B payload to structured metrics.

    Full protobuf decode (vendored Eclipse Tahu schema): per metric returns name,
    alias, datatype (Int/Float/Bool/String/DateTime/DataSet/Template…), value,
    timestamp, and is_historical / is_null flags.

    Args:
        payload: Raw Sparkplug B protobuf bytes as a string, ``base64`` (default) or ``hex``.
        encoding: 'base64' or 'hex'.
        alias_map: Optional {alias: name} (from a prior BIRTH) so alias-only
            NDATA/DDATA metrics resolve to names.

    Returns dict: {encoding:'sparkplug_b', timestamp, seq, uuid, metric_count,
        historical_count, metrics:[{name, alias, datatype, value, timestamp,
        is_historical, is_null}]}.

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
