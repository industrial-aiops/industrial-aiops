"""Read-only problem-surfacing MCP tools (threshold + statistical anomaly)."""

from typing import Optional

from iaiops.core.brain import analysis
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def health_summary(
    endpoint: Optional[str] = None,
    node_ids: Optional[list] = None,
    thresholds: Optional[dict] = None,
) -> dict:
    """[READ] Classify OPC-UA tag node-ids against warn/alarm thresholds.

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
def anomaly_scan(
    node_id: str,
    endpoint: Optional[str] = None,
    samples: int = 20,
    interval_ms: int = 200,
    sigma: float = 3.0,
) -> dict:
    """[READ] Sample a node over a bounded window and flag statistical outliers.

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
