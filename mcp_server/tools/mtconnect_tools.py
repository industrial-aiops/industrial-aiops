"""MTConnect MCP tools — royalty-free CNC machine-tool telemetry (read-only).

All MTConnect tools are READ-ONLY by the standard's specification; every tool is
governed at risk_level='low'.
"""

from typing import Optional

from iaiops.connectors.mtconnect import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_probe(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] The device model: devices → components → data items.

    The MTConnect 'schema' — what the machine can report. Call this first to
    discover dataItem ids/types before reading values.

    Args:
        endpoint: Endpoint name from config (protocol must be 'mtconnect').

    Returns dict: {endpoint, device_count, devices:[{name, uuid, component_count,
        components:[{component, id, name, data_items:[{id, type, category, name, units}]}]}]}.

    Example: mtconnect_probe(endpoint="vmc1").
    """
    return ops.mtconnect_probe(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_current(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Latest value of every data item (a snapshot of the machine now).

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, observation_count, observations:[{data_item_id, type,
        name, timestamp, sequence, value}]}.

    Example: mtconnect_current(endpoint="vmc1").
    """
    return ops.mtconnect_current(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_sample(endpoint: Optional[str] = None, count: int = 100) -> dict:
    """[READ][risk=low] A BOUNDED stream of recent observations (history).

    Args:
        endpoint: Endpoint name from config.
        count: Max observations to request (1..500, capped server-side).

    Returns dict: {endpoint, requested_count, observation_count,
        observations:[{data_item_id, type, name, timestamp, sequence, value}]}.

    Example: mtconnect_sample(endpoint="vmc1", count=200).
    """
    return ops.mtconnect_sample(_target(endpoint), count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_assets(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Assets the agent knows (cutting tools, fixtures, programs).

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, asset_count, assets:[{asset_type, asset_id, timestamp}]}.

    Example: mtconnect_assets(endpoint="vmc1").
    """
    return ops.mtconnect_assets(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_oee_snapshot(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Availability / Execution / mode / program (OEE inputs).

    Surfaces the live data items an availability/performance calc needs. Does NOT
    compute a single OEE % (needs planned-time + ideal-cycle context MTConnect
    doesn't expose).

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, availability, execution, controller_mode, program,
        available (bool), running (bool), verdict ('running'|'available_idle'|'down')}.

    Example: mtconnect_oee_snapshot(endpoint="vmc1").
    """
    return ops.mtconnect_oee_snapshot(_target(endpoint))
