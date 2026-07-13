"""PROFINET MCP tools — DCP discovery/identify/asset + one MOC-gated Set (pnio-dcp).

Read tools are governed at risk_level='low' (non-destructive). PROFINET-DCP is a
layer-2 broadcast: discovery + identify — NO RT cyclic data. ``profinet_dcp_set`` is
risk_level='high' (MOC): it re-addresses a live station's name/IP, captures the
BEFORE addressing, records an undo descriptor, and defaults to dry_run. Blink/reset
stay out of scope. pnio-dcp is an OPTIONAL extra (``pip install iaiops[profinet]``)
imported lazily; it also needs raw-socket access (root/admin/CAP_NET_RAW) on the NIC
on the PROFINET subnet. When unavailable, every tool returns a teaching error dict.
"""

from typing import Any, Optional

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


def _profinet_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of an applied profinet_dcp_set: restore the captured BEFORE addressing."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if not before:
        return None
    return {
        "tool": "profinet_dcp_set",
        "params": {
            "endpoint": params.get("endpoint"),
            "mac": params.get("mac"),
            "set_name": before.get("name_of_station"),
            "set_ip": before.get("ip"),
            "netmask": before.get("netmask"),
            "gateway": before.get("gateway"),
            "dry_run": False,
        },
        "note": "Restore prior PROFINET station addressing (undo of profinet_dcp_set).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_profinet_undo)
@tool_errors("dict")
def profinet_dcp_set(
    mac: str,
    set_name: Optional[str] = None,
    set_ip: Optional[str] = None,
    netmask: Optional[str] = None,
    gateway: Optional[str] = None,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] DCP Set — re-address one PROFINET station (off by default).

    OT-DANGEROUS. Defaults to dry_run=True (nothing set). Re-addresses a live
    station's name-of-station and/or IP suite via a unicast DCP Set (can disrupt the
    IO connection). Captures the BEFORE addressing (by MAC) and records an undo
    descriptor. Set dry_run=False AND record an approver (OPCUA_AUDIT_APPROVED_BY) to
    apply. 未经授权勿对生产控制系统写入.

    Args:
        mac: Target station MAC, e.g. '00:1b:1b:12:34:56' (from profinet_discover).
        set_name: New name-of-station (omit to leave unchanged).
        set_ip: New IP address (omit to leave the IP suite unchanged).
        netmask: New subnet mask (used with set_ip).
        gateway: New default gateway (used with set_ip).
        endpoint: Endpoint name from config (protocol 'profinet').
        dry_run: When True (default) returns a preview without setting anything.

    Returns dict: dry-run → {mac, dry_run:true, before, would_set, note};
        applied → {mac, dry_run:false, before, set, applied:true, _undo_id}.

    Example (preview): profinet_dcp_set(mac="00:1b:1b:12:34:56", set_name="plc-new").
    """
    return ops.profinet_dcp_set(
        _target(endpoint),
        mac,
        set_name=set_name,
        set_ip=set_ip,
        netmask=netmask,
        gateway=gateway,
        dry_run=dry_run,
    )
