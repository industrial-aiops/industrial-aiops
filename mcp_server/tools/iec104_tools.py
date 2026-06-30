"""IEC 60870-5-104 MCP tools — read-only substation/RTU telemetry (c104 extra).

All tools are governed at risk_level='low' (non-destructive monitor direction).
Control-direction commands are intentionally NOT exposed in this preview. c104 is
an OPTIONAL extra (``pip install iaiops[iec104]``) imported lazily; when missing,
every tool returns a teaching error dict. Preview — binding/API shape unverified
against a live RTU.
"""

from typing import Optional

from iaiops.connectors.iec104 import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iec104_connection_info(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Connect and report IEC-104 link status + discovered stations.

    Args:
        endpoint: Endpoint name from config (protocol 'iec104'); omit for default.

    Returns dict: {endpoint, host, port, connected, configured_common_address,
        station_count, common_addresses[]}.

    Example: iec104_connection_info(endpoint="rtu1").
    """
    return ops.iec104_connection_info(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iec104_interrogate(
    common_address: Optional[int] = None, endpoint: Optional[str] = None
) -> dict:
    """[READ][risk=low] General interrogation: all monitored points of a station (ASDU CA).

    Args:
        common_address: ASDU common address; omit for the configured/first station.
        endpoint: Endpoint name from config (protocol 'iec104').

    Returns dict: {endpoint, common_address, point_count, points:[{io_address, type,
        value, quality, recorded_at}]}.

    Example: iec104_interrogate(common_address=1, endpoint="rtu1").
    """
    return ops.iec104_interrogate(_target(endpoint), common_address)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iec104_read_point(
    io_address: int, common_address: Optional[int] = None, endpoint: Optional[str] = None
) -> dict:
    """[READ][risk=low] Read one monitored point by information-object address (IOA).

    Args:
        io_address: The point's information-object address (IOA).
        common_address: ASDU common address; omit for the configured/first station.
        endpoint: Endpoint name from config (protocol 'iec104').

    Returns dict: {endpoint, common_address, found, io_address, type, value, quality,
        recorded_at}.

    Example: iec104_read_point(io_address=1001, common_address=1, endpoint="rtu1").
    """
    return ops.iec104_read_point(_target(endpoint), io_address, common_address)
