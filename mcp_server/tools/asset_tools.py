"""Active asset-inventory MCP tool (READ-ONLY, IEC 62443-flavored).

Non-destructive (risk_level='low'). Actively connects to each configured (or
named) endpoint and reads its identity to build an asset register. This is ACTIVE
fingerprinting via our clients — NOT passive SPAN/tap discovery (roadmap).
"""

from typing import Optional

from iaiops.core.brain import asset_inventory as ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _manager, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def asset_inventory(endpoints: Optional[list] = None) -> dict:
    """[READ][risk=low] Actively fingerprint endpoints into an asset register.

    Connects to each target with our own protocol client and reads its identity
    call (S7 CPU info, EtherNet/IP controller info, OPC-UA server build info,
    Modbus device identification FC43, Mitsubishi CPU type, MTConnect device
    model), aggregating vendor/model/firmware/serial per device.

    Honest scope: ACTIVE fingerprinting (we connect to each device), NOT passive
    SPAN/tap discovery. Only finds devices we are configured to reach.

    Args:
        endpoints: Endpoint names to fingerprint; omit to fingerprint ALL
            configured endpoints.

    Returns dict: {asset_count, reachable_count, unreachable_count, method:
        'active_fingerprint', assets:[{endpoint, protocol, address, vendor, model,
        firmware, serial, reachable, last_seen, error}]}.

    Example: asset_inventory(endpoints=["press1","cell5"]).
    """
    mgr = _manager()
    names = endpoints if endpoints else mgr.list_targets()
    targets = [mgr.target(n) for n in names]
    return ops.asset_inventory(targets)
