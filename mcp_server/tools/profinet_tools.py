"""PROFINET MCP tools — DCP discovery/identify/asset (READ-ONLY, via pnio-dcp).

All tools are governed at risk_level='low' (non-destructive). PROFINET-DCP is a
layer-2 broadcast: discovery + identify only — NO RT cyclic data, and the
disruptive DCP *Set* services (set-name/set-ip/blink/reset) are intentionally not
exposed. pnio-dcp is an OPTIONAL extra (``pip install iaiops[profinet]``) imported
lazily; it also needs raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the
PROFINET subnet. When unavailable, every tool returns a teaching error dict.
"""

from typing import Optional

from iaiops.connectors.profinet import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def profinet_discover(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] DCP IdentifyAll — every PROFINET station on the segment.

    One layer-2 broadcast surfaces all stations without connecting to any. Needs
    raw-socket access on the NIC on the PROFINET subnet (pnio-dcp extra); degrades
    to a teaching error dict when pnio-dcp/permission/NIC is missing.

    Args:
        endpoint: Endpoint name from config (protocol 'profinet'); omit for default.

    Returns dict: {endpoint, local_ip, station_count, stations:[{name_of_station,
        mac, ip, netmask, gateway, vendor_id, device_id, device_role_raw,
        device_roles[], device_family}]}.

    Example: profinet_discover(endpoint="cell1").
    """
    return ops.profinet_discover(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def profinet_identify_station(name_of_station: str, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Identify one station by its PROFINET name-of-station.

    Args:
        name_of_station: Exact (case-insensitive) PROFINET station name, e.g. 'plc1'.
        endpoint: Endpoint name from config (protocol 'profinet').

    Returns dict: {endpoint, found (bool), name_of_station, mac, ip, netmask,
        gateway, vendor_id, device_id, device_roles[], device_family}.

    Example: profinet_identify_station(name_of_station="et200sp-1", endpoint="cell1").
    """
    return ops.profinet_identify_station(_target(endpoint), name_of_station)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def profinet_station_params(mac: str, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Targeted DCP Get for one station (by MAC): name + IP suite.

    Args:
        mac: The station's MAC address, e.g. '00:1b:1b:12:34:56'.
        endpoint: Endpoint name from config (protocol 'profinet').

    Returns dict: {endpoint, mac, found (bool), name_of_station, ip, netmask, gateway}.

    Example: profinet_station_params(mac="00:1b:1b:12:34:56", endpoint="cell1").
    """
    return ops.profinet_station_params(_target(endpoint), mac)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def profinet_asset_inventory(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] PROFINET asset register from a DCP IdentifyAll sweep.

    Segment-wide, read-only — no per-device connection. Decodes the DCP device-role
    bitmask so IO-controllers vs IO-devices are distinguished.

    Args:
        endpoint: Endpoint name from config (protocol 'profinet').

    Returns dict: {endpoint, asset_count, io_controller_count, io_device_count,
        assets:[{name_of_station, mac, ip, vendor_id, device_id, roles[], family}],
        method:'dcp_identify_all'}.

    Example: profinet_asset_inventory(endpoint="cell1").
    """
    return ops.profinet_asset_inventory(_target(endpoint))
