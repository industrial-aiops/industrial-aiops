"""BACnet/IP MCP tools — read-only facility / HVAC monitoring (bacnet/BAC0 extra).

Governed at risk_level='low' (read-only). Writes (present-value with priority) are
intentionally NOT exposed — overriding a live building-control point is dangerous.
BAC0 is an OPTIONAL extra (``pip install iaiops[bacnet]``) imported lazily; when
missing, every tool returns a teaching error dict. Preview — binding/API shape
unverified against live building gear.
"""

from typing import Optional

from iaiops.connectors.bacnet import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bacnet_discover(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Who-Is broadcast: discover BACnet devices on the local network.

    Args:
        endpoint: Endpoint name from config (protocol 'bacnet'); omit for default.

    Returns dict: {endpoint, local_interface, device_count,
        devices:[{device_id, address}]}.

    Example: bacnet_discover(endpoint="ahu-net").
    """
    return ops.bacnet_discover(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bacnet_object_list(address: str, device_id: int, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Read a device's object list (its BACnet points/objects).

    Args:
        address: BACnet device address (from bacnet_discover), e.g. '192.168.1.10'.
        device_id: BACnet device instance id (from bacnet_discover).
        endpoint: Endpoint name from config (protocol 'bacnet').

    Returns dict: {endpoint, address, device_id, object_count,
        objects:[{object_type, instance}]}.

    Example: bacnet_object_list(address="192.168.1.10", device_id=1001, endpoint="ahu-net").
    """
    return ops.bacnet_object_list(_target(endpoint), address, device_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bacnet_read_property(
    address: str, object_type: str, instance: int,
    bacnet_property: str = "presentValue", endpoint: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Read one property of one BACnet object (default presentValue).

    Args:
        address: BACnet device address, e.g. '192.168.1.10'.
        object_type: BACnet object type, e.g. 'analogInput', 'binaryValue'.
        instance: Object instance number.
        bacnet_property: Property to read (default 'presentValue').
        endpoint: Endpoint name from config (protocol 'bacnet').

    Returns dict: {endpoint, address, object_type, instance, property, value}.

    Example: bacnet_read_property(address="192.168.1.10", object_type="analogInput",
        instance=1, endpoint="ahu-net").
    """
    return ops.bacnet_read_property(
        _target(endpoint), address, object_type, instance, bacnet_property
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bacnet_read_points(address: str, device_id: int, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Read presentValue of all monitor-relevant points of a device.

    Reads the object list, filters to analog/binary/multistate I/O/value objects,
    and reads each presentValue — the HVAC/facility snapshot.

    Args:
        address: BACnet device address (from bacnet_discover).
        device_id: BACnet device instance id (from bacnet_discover).
        endpoint: Endpoint name from config (protocol 'bacnet').

    Returns dict: {endpoint, address, device_id, point_count, skipped_non_readable,
        points:[{object_type, instance, present_value}]}.

    Example: bacnet_read_points(address="192.168.1.10", device_id=1001, endpoint="ahu-net").
    """
    return ops.bacnet_read_points(_target(endpoint), address, device_id)
