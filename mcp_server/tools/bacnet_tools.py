"""BACnet/IP MCP tools — facility / HVAC monitoring + one MOC-gated write (BAC0 extra).

Read tools are governed at risk_level='low'. ``bacnet_write_property`` is
risk_level='high' (MOC): overriding a live building-control point (present-value at a
priority, or relinquishing it) is OT-dangerous — it captures the BEFORE value,
records an undo descriptor, and defaults to dry_run. BAC0 is an OPTIONAL extra
(``pip install iaiops[bacnet]``) imported lazily; when missing, every tool returns a
teaching error dict. Preview — binding/API shape unverified against live gear.
"""

from typing import Any, Optional

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


def _bacnet_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied bacnet_write_property: restore the captured BEFORE value."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if before is None:
        return None
    return {
        "tool": "bacnet_write_property",
        "params": {
            "endpoint": params.get("endpoint"),
            "address": params.get("address"),
            "object_type": params.get("object_type"),
            "instance": params.get("instance"),
            "value": before,
            "priority": params.get("priority"),
            "bacnet_property": params.get("bacnet_property", "presentValue"),
            "relinquish": False,
            "dry_run": False,
        },
        "note": "Restore prior BACnet property value (undo of bacnet_write_property).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_bacnet_undo)
@tool_errors("dict")
def bacnet_write_property(
    address: str,
    object_type: str,
    instance: int,
    value: Any,
    priority: Optional[int] = None,
    bacnet_property: str = "presentValue",
    relinquish: bool = False,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Write ONE BACnet object property (off by default).

    OT-DANGEROUS. Defaults to dry_run=True (nothing written). Overriding a live
    building-control point (present-value, optionally at a BACnet priority 1..16, or
    relinquishing that priority) can move real HVAC/plant. Captures the BEFORE value
    (read-back) and records an undo descriptor. Set dry_run=False AND record an
    approver (OPCUA_AUDIT_APPROVED_BY) to apply. 未经授权勿对生产控制系统写入.

    Args:
        address: BACnet device address (from bacnet_discover), e.g. '192.168.1.10'.
        object_type: BACnet object type, e.g. 'analogOutput', 'binaryValue'.
        instance: Object instance number.
        value: Value to write (ignored when relinquish=True).
        priority: BACnet write priority 1..16 (omit for the device default).
        bacnet_property: Property to write (default 'presentValue').
        relinquish: When True, write 'null' to relinquish this priority slot.
        endpoint: Endpoint name from config (protocol 'bacnet').
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {address, object_type, instance, property, priority,
        relinquish, dry_run:true, before, would_write, request, note};
        applied → {..., dry_run:false, before, written, applied:true, _undo_id}.

    Example (preview): bacnet_write_property(address="192.168.1.10",
        object_type="analogOutput", instance=1, value=21.0, priority=8).
    """
    return ops.bacnet_write_property(
        _target(endpoint), address, object_type, instance, value,
        priority=priority, bacnet_property=bacnet_property,
        relinquish=relinquish, dry_run=dry_run,
    )
