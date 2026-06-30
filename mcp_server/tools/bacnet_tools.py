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


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bacnet_cov_subscribe(
    address: str, object_type: str, instance: int,
    max_notifications: int = 20, timeout_s: int = 30, lifetime_s: int = 300,
    endpoint: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Bounded Change-of-Value capture for one BACnet object.

    Subscribes to the object's COV, collects up to max_notifications notifications
    OR until timeout_s elapses (whichever first), then always unsubscribes. Never
    an open subscription — both count and wall-clock are hard-capped.

    Args:
        address: BACnet device address (from bacnet_discover), e.g. '192.168.1.10'.
        object_type: BACnet object type, e.g. 'analogInput', 'binaryValue'.
        instance: Object instance number.
        max_notifications: Stop after this many notifications (capped, default 20).
        timeout_s: Stop after this many seconds (capped, default 30).
        lifetime_s: COV subscription lifetime requested of the device (default 300).
        endpoint: Endpoint name from config (protocol 'bacnet').

    Returns dict: {endpoint, address, object_type, instance, requested_max,
        timeout_s, lifetime_s, notification_count, terminated_reason,
        changes:[{property, value, wall_clock}]}.

    Example: bacnet_cov_subscribe(address="192.168.1.10", object_type="analogInput",
        instance=1, max_notifications=5, timeout_s=20, endpoint="ahu-net").
    """
    return ops.bacnet_cov_subscribe(
        _target(endpoint), address, object_type, instance,
        max_notifications, timeout_s, lifetime_s,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bacnet_read_trend_log(
    address: str, instance: int, count: int = 100, newest_first: bool = True,
    endpoint: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Read buffered records from a device's BACnet TrendLog object.

    A TrendLog object logs a point's value over time on the device itself; this
    reads its logBuffer with a single bounded ReadRange. Read-only historical trend.

    Args:
        address: BACnet device address (from bacnet_discover), e.g. '192.168.1.10'.
        instance: TrendLog object instance number (from bacnet_object_list).
        count: Maximum records to return (capped, default 100).
        newest_first: Return most-recent records first (default True).
        endpoint: Endpoint name from config (protocol 'bacnet').

    Returns dict: {endpoint, address, instance, requested_count, newest_first,
        record_count, records:[{timestamp, value}]}.

    Example: bacnet_read_trend_log(address="192.168.1.10", instance=1, count=50,
        endpoint="ahu-net").
    """
    return ops.bacnet_read_trend_log(
        _target(endpoint), address, instance, count, newest_first
    )
