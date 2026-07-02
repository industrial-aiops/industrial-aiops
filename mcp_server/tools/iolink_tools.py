"""IO-Link MCP tools — sensor-level visibility via the master's JSON interface.

The IO-Link connector is READ-ONLY in v1 (no setdata/write services exposed);
every tool is governed at risk_level='low'.
"""

from typing import Optional

from iaiops.connectors.iolink import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iolink_master_info(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] IO-Link master identity (productcode/serial/hw/sw revision).

    Reads the master's /deviceinfo tree over its JSON interface (ifm IoT-Core
    envelope or plain REST, per the endpoint's flavor).

    Args:
        endpoint: Endpoint name from config (protocol must be 'iolink').

    Returns dict: {endpoint, flavor, master:{productcode, serialnumber,
        hwrevision, swrevision}, unavailable?:{field: error}}.

    Example: iolink_master_info(endpoint="master1").
    """
    return ops.master_info(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iolink_ports(endpoint: Optional[str] = None, count: int = 8) -> dict:
    """[READ][risk=low] BOUNDED port sweep: mode/status + connected device identity.

    Call this first to see which ports carry an IO-Link device before reading
    process data.

    Args:
        endpoint: Endpoint name from config.
        count: Ports to sweep (1..32, capped server-side).

    Returns dict: {endpoint, ports_checked, ports_present, devices_connected,
        ports:[{port, present, mode, device_connected, device_status, vendorid,
        deviceid, productname}]}.

    Example: iolink_ports(endpoint="master1", count=8).
    """
    return ops.ports(_target(endpoint), count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iolink_device_info(port: int, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Identity of the IO-Link device on one master port.

    Args:
        port: Master port number (1..32).
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, port, device:{vendorid, deviceid, productname,
        serial, status}, unavailable?:{field: error}}.

    Example: iolink_device_info(port=1, endpoint="master1").
    """
    return ops.device_info(_target(endpoint), port)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iolink_read_pdin(port: int, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Process-data-in of one port: raw hex + decoded byte array.

    The byte layout is device-specific — decode per the device's IODD.

    Args:
        port: Master port number (1..32).
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, port, pdin_hex, bytes:[int], byte_count, note}.

    Example: iolink_read_pdin(port=1, endpoint="master1").
    """
    return ops.read_pdin(_target(endpoint), port)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iolink_read_isdu(
    port: int, index: int, subindex: int = 0, endpoint: Optional[str] = None
) -> dict:
    """[READ][risk=low] ISDU acyclic parameter read (iolreadacyclic) — bounded.

    Args:
        port: Master port number (1..32).
        index: ISDU parameter index (0..65535).
        subindex: ISDU subindex (0..255, default 0).
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, port, index, subindex, value} (value typically a
        hex string of the parameter octets; master-dependent).

    Example: iolink_read_isdu(port=1, index=16, endpoint="master1").
    """
    return ops.read_isdu(_target(endpoint), port, index, subindex)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iolink_scan(endpoint: Optional[str] = None, count: int = 8) -> dict:
    """[READ][risk=low] One-shot BOUNDED snapshot: master identity + all ports.

    Args:
        endpoint: Endpoint name from config.
        count: Ports to sweep (1..32, capped server-side).

    Returns dict: {endpoint, flavor, master:{...}, ports_checked, ports_present,
        devices_connected, ports:[{port, present, mode, device_connected, ...}]}.

    Example: iolink_scan(endpoint="master1").
    """
    return ops.scan(_target(endpoint), count)
