"""DEPRECATED aliases for the OPC-UA problem-surfacing tools.

``health_summary`` and ``anomaly_scan`` are OPC-UA-specific and moved to
``mcp_server.tools.opcua_tools`` as ``opcua_health_summary`` /
``opcua_anomaly_scan`` (registered with the opcua protocol module only).
These brain-registered aliases delegate to the same implementations (renamed
in 0.10.0). They are still registered and will be removed in a future release
(target: 1.0.0).
"""

from typing import Optional

from iaiops.core.brain import analysis
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors

_HEALTH_SUMMARY_DEPRECATION = (
    "renamed to opcua_health_summary in 0.10.0; this deprecated alias is still "
    "registered and will be removed in a future release (target: 1.0.0)"
)
_ANOMALY_SCAN_DEPRECATION = (
    "renamed to opcua_anomaly_scan in 0.10.0; this deprecated alias is still "
    "registered and will be removed in a future release (target: 1.0.0)"
)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def health_summary(
    endpoint: Optional[str] = None,
    node_ids: Optional[list[str]] = None,
    thresholds: Optional[dict[str, dict[str, float]]] = None,
) -> dict:
    """[DEPRECATED → opcua_health_summary][READ][risk=low] Classify OPC-UA tags.

    Classifies tag node-ids against warn/alarm thresholds. Returns
    ok/warn/alarm/unknown counts plus the offending tags. Thresholds
    come from config tags, or per-ref overrides in ``thresholds``.

    Args:
        endpoint: Endpoint name from config.
        node_ids: Tag node ids to evaluate; omit to use configured tags.
        thresholds: Optional {ref: {warn_high, alarm_high, warn_low, alarm_low}}.
    """
    out = analysis.health_summary(_target(endpoint), node_ids, thresholds)
    return {**out, "deprecated": _HEALTH_SUMMARY_DEPRECATION}


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def anomaly_scan(
    node_id: str,
    endpoint: Optional[str] = None,
    samples: int = 20,
    interval_ms: int = 200,
    sigma: float = 3.0,
) -> dict:
    """[DEPRECATED → opcua_anomaly_scan][READ][risk=low] Statistical outlier scan.

    Samples a node over a bounded window and flags statistical outliers.
    Computes mean/stddev/min/max and flags samples outside mean ± sigma*stddev.
    Simple statistics only — no ML, no persisted model.

    Args:
        node_id: The OPC-UA node id to scan.
        endpoint: Endpoint name from config.
        samples: Max samples (capped server-side).
        interval_ms: Delay between samples in milliseconds.
        sigma: Outlier band width in standard deviations.
    """
    out = analysis.anomaly_scan(_target(endpoint), node_id, samples, interval_ms, sigma)
    return {**out, "deprecated": _ANOMALY_SCAN_DEPRECATION}
