"""Read-only Modbus-TCP MCP tools (covers many domestic 国产 PLCs)."""

from typing import Optional

from iaiops.connectors.modbus import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def modbus_read_holding(
    address: int, endpoint: Optional[str] = None, count: int = 1, decode: str = "uint16"
) -> dict:
    """[READ] Read holding registers (FC03) with a decode hint.

    Args:
        address: Starting register address.
        endpoint: Endpoint name from config.
        count: Number of registers (capped server-side).
        decode: raw|uint16|int16|uint32|int32|float32.
    """
    return ops.modbus_read_holding(_target(endpoint), address, count, decode)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def modbus_read_input(
    address: int, endpoint: Optional[str] = None, count: int = 1, decode: str = "uint16"
) -> dict:
    """[READ] Read input registers (FC04) with a decode hint.

    Args:
        address: Starting register address.
        endpoint: Endpoint name from config.
        count: Number of registers (capped server-side).
        decode: raw|uint16|int16|uint32|int32|float32.
    """
    return ops.modbus_read_input(_target(endpoint), address, count, decode)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def modbus_read_coils(address: int, endpoint: Optional[str] = None, count: int = 1) -> dict:
    """[READ] Read coils (FC01) — digital outputs, read-only here.

    Args:
        address: Starting coil address.
        endpoint: Endpoint name from config.
        count: Number of coils.
    """
    return ops.modbus_read_coils(_target(endpoint), address, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def modbus_read_discrete(address: int, endpoint: Optional[str] = None, count: int = 1) -> dict:
    """[READ] Read discrete inputs (FC02) — read-only digital inputs.

    Args:
        address: Starting discrete-input address.
        endpoint: Endpoint name from config.
        count: Number of inputs.
    """
    return ops.modbus_read_discrete(_target(endpoint), address, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def modbus_health_summary(
    endpoint: Optional[str] = None,
    addresses: Optional[list] = None,
    thresholds: Optional[dict] = None,
    register_type: str = "holding",
) -> dict:
    """[READ] Classify Modbus registers against warn/alarm thresholds.

    Mirrors the OPC-UA health_summary classifier. Returns ok/warn/alarm/unknown
    counts plus offenders.

    Args:
        endpoint: Endpoint name from config.
        addresses: Register addresses to evaluate; omit to use configured tags.
        thresholds: Optional {address_str: {warn_high, alarm_high, ...}}.
        register_type: holding|input.
    """
    return ops.modbus_health_summary(_target(endpoint), addresses, thresholds, register_type)
