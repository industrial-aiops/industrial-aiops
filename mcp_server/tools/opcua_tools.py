"""Read-only OPC-UA MCP tools.

Every tool is wrapped with ``@governed_tool`` (the iaiops harness): policy
pre-check, budget/runaway guard, risk-tier gate, and audit logging to
~/.iaiops/audit.db. These are all READ tools (risk_level='low').
"""

from typing import Optional

from iaiops.connectors.opcua import diagnostics as diag
from iaiops.connectors.opcua import discovery as disc
from iaiops.connectors.opcua import ops
from iaiops.core.brain import analysis
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_server_info(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] OPC-UA server status, build info, and namespace array.

    Args:
        endpoint: Endpoint name from config; omit to use the default endpoint.
    """
    return ops.server_info(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def opcua_browse(
    node_id: str = "i=85", endpoint: Optional[str] = None, depth: int = 2
) -> list:
    """[READ][risk=low] Browse the OPC-UA node tree from a node id (bounded depth).

    Args:
        node_id: Root node id (default i=85, the Objects folder).
        endpoint: Endpoint name from config.
        depth: Bounded browse depth (capped server-side).
    """
    return ops.browse(_target(endpoint), node_id, depth)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_read_node(node_id: str, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Read one node: value, datatype, source timestamp, status code.

    Args:
        node_id: The OPC-UA node id to read (e.g. ns=2;i=5).
        endpoint: Endpoint name from config.
    """
    return ops.read_node(_target(endpoint), node_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def opcua_read_many(node_ids: list[str], endpoint: Optional[str] = None) -> list:
    """[READ][risk=low] Batch-read multiple node ids in one session (bounded count).

    Args:
        node_ids: List of OPC-UA node ids to read.
        endpoint: Endpoint name from config.
    """
    return ops.read_many(_target(endpoint), node_ids)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_subscribe_sample(
    node_id: str,
    endpoint: Optional[str] = None,
    samples: int = 5,
    interval_ms: int = 500,
    timeout_s: int = 30,
) -> dict:
    """[READ][risk=low] Sample a node a BOUNDED number of times, then return (never loops).

    Args:
        node_id: The OPC-UA node id to sample.
        endpoint: Endpoint name from config.
        samples: Max number of readings (capped server-side).
        interval_ms: Delay between readings in milliseconds.
        timeout_s: Hard wall-clock cap in seconds (capped server-side).
    """
    return ops.subscribe_sample(_target(endpoint), node_id, samples, interval_ms, timeout_s)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_read_alarms(
    endpoint: Optional[str] = None, node_id: str = "i=85", depth: int = 4
) -> dict:
    """[READ][risk=low] Best-effort surfacing of active alarm/condition booleans.

    Browses the address space (bounded) for alarm-like boolean nodes reading
    True. Full OPC-UA Alarms & Conditions event subscriptions are not modelled
    in this preview; returns a clear note when nothing alarm-like is found.

    Args:
        endpoint: Endpoint name from config.
        node_id: Root node id to scan from (default i=85).
        depth: Bounded scan depth.
    """
    return ops.read_alarms(_target(endpoint), node_id, depth)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_read_history(
    node_id: str,
    endpoint: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_points: int = 1000,
) -> dict:
    """[READ][risk=low] OPC-UA Historical Access (HDA): raw historical values over a window.

    Reads stored history for a node via the server's HistoryRead service, bounded
    by ``max_points``. Returns a clear 'unsupported' note when the server does not
    historize the node (no crash).

    Args:
        node_id: The OPC-UA node id to read history for (e.g. ns=2;i=5).
        endpoint: Endpoint name from config.
        start: ISO-8601 window start (default: 1 hour before end).
        end: ISO-8601 window end (default: now).
        max_points: Max points to return (capped server-side at 2000).

    Returns dict: {node_id, supported (bool), start, end, count,
        values:[{value, source_timestamp, status_code}]}.

    Example: opcua_read_history(node_id="ns=2;i=5", start="2026-06-28T08:00:00Z").
    """
    return ops.read_history(_target(endpoint), node_id, start, end, max_points)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_diagnose_connection(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Diagnose why an OPC-UA endpoint won't connect — a classified verdict.

    Attempts a connect (no writes, disconnects immediately) and classifies any
    failure into the well-known OPC-UA buckets instead of returning a raw error,
    each with a concrete next step:
    certificate (server doesn't trust our client cert) · auth (user/password) ·
    security_policy (policy/mode mismatch) · port_closed · dns · firewall_timeout ·
    unreachable · config (bad endpoint_url / connector not installed) · ok.

    Args:
        endpoint: Endpoint name from config; omit to use the default endpoint.

    Returns dict: {endpoint, reachable (bool), class, diagnosis, remediation, detail}.
    """
    return diag.diagnose_connection(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_discover_tags(
    endpoint: Optional[str] = None, root: str = "i=85", max_depth: int = 6,
    include_standard: bool = False,
) -> dict:
    """[READ][risk=low] Auto-discover OPC-UA tags and build a semantic asset model.

    Walks the address space, collects every Variable node, and enriches each with
    datatype / value / engineering-unit / a heuristic semantic class (temperature,
    pressure, flow, setpoint, alarm, state, …) and a suggested clean alias. Tags
    are grouped into assets by their browse path, and a naming-quality report
    flags alias collisions + cryptic names. Aliases are ADVISORY — nothing is
    written back to the server (a server-side rename would be OT-dangerous).

    Args:
        endpoint: Endpoint name from config; omit to use the default endpoint.
        root: Root node id to discover from (default i=85, the Objects folder).
        max_depth: Bounded recursion depth (capped server-side at 8).
        include_standard: Include OPC-UA namespace-0 server infrastructure
            (default False — only real process tags in vendor namespaces).

    Returns dict: {endpoint, root, tag_count, asset_count,
        assets:[{asset, tag_count, classes, tags:[{node_id, browse_name,
        browse_path, datatype, value, unit, writable, class, suggested_alias}]}],
        naming_quality:{alias_collisions, cryptic_names, verdict}}.
    """
    return disc.tag_discovery(_target(endpoint), root, max_depth, include_standard)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_health_summary(
    endpoint: Optional[str] = None,
    node_ids: Optional[list[str]] = None,
    thresholds: Optional[dict[str, dict[str, float]]] = None,
) -> dict:
    """[READ][risk=low] Classify OPC-UA tag node-ids against warn/alarm thresholds.

    Returns ok/warn/alarm/unknown counts plus the offending tags. Thresholds
    come from config tags, or per-ref overrides in ``thresholds``.

    Args:
        endpoint: Endpoint name from config.
        node_ids: Tag node ids to evaluate; omit to use configured tags.
        thresholds: Optional {ref: {warn_high, alarm_high, warn_low, alarm_low}}.
    """
    return analysis.health_summary(_target(endpoint), node_ids, thresholds)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def opcua_anomaly_scan(
    node_id: str,
    endpoint: Optional[str] = None,
    samples: int = 20,
    interval_ms: int = 200,
    sigma: float = 3.0,
) -> dict:
    """[READ][risk=low] Sample a node over a bounded window and flag statistical outliers.

    Computes mean/stddev/min/max and flags samples outside mean ± sigma*stddev.
    Simple statistics only — no ML, no persisted model.

    Args:
        node_id: The OPC-UA node id to scan.
        endpoint: Endpoint name from config.
        samples: Max samples (capped server-side).
        interval_ms: Delay between samples in milliseconds.
        sigma: Outlier band width in standard deviations.
    """
    return analysis.anomaly_scan(_target(endpoint), node_id, samples, interval_ms, sigma)
