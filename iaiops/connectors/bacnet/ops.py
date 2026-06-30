"""BACnet/IP operations — read-only facility / HVAC monitoring (via the ``bacnet`` extra).

BACnet/IP (ASHRAE 135) is the dominant building-automation protocol — HVAC,
lighting, metering, 厂务/facility plant. This connector is **read-only monitoring**:
device discovery (Who-Is), object-list browse, and property reads (present-value of
analog/binary/multistate points). Writes (present-value with priority / relinquish)
are OT-dangerous for live building control and intentionally NOT exposed here.

``BAC0`` (over bacpypes3) is an OPTIONAL extra imported lazily in
:func:`iaiops.core.runtime.connection._build_bacnet_network`. The BAC0 surface is
duck-typed and 待核实 (unverified against live gear) — the ops below build BACnet
request strings and normalize results defensively, and are fully mock-testable.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.runtime.connection import OTConnectionError, bacnet_session

MAX_DEVICES = 2000
MAX_OBJECTS = 2000
MAX_POINT_READS = 500

# Monitor-relevant object types whose presentValue is worth a bulk read.
READABLE_TYPES = (
    "analogInput", "analogOutput", "analogValue",
    "binaryInput", "binaryOutput", "binaryValue",
    "multiStateInput", "multiStateOutput", "multiStateValue",
)


def _norm_device(item: Any) -> dict:
    """Normalize a BAC0 who_is result (tuple/list/obj) to {device_id, address}."""
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        # BAC0 commonly yields (device_id, address) or (address, device_id).
        a, b = item[0], item[1]
        dev_id = a if _opt_int(a) is not None and not _looks_like_addr(a) else b
        addr = b if dev_id is a else a
        return {"device_id": _opt_int(dev_id), "address": s(addr, 64)}
    return {
        "device_id": _opt_int(getattr(item, "device_id", getattr(item, "deviceId", None))),
        "address": s(getattr(item, "address", item), 64),
    }


def _looks_like_addr(value: Any) -> bool:
    """Heuristic: a BACnet address has a dot/colon; a device id is a bare int."""
    text = str(value)
    return ("." in text) or (":" in text)


def _opt_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_object(item: Any) -> dict:
    """Normalize an object-list entry (objectType, instance) tuple/obj."""
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return {"object_type": s(item[0], 32), "instance": _opt_int(item[1])}
    return {
        "object_type": s(getattr(item, "objectType", getattr(item, "object_type", "")), 32),
        "instance": _opt_int(getattr(item, "instance", getattr(item, "objectInstance", None))),
    }


def bacnet_discover(target: Any) -> dict:
    """[READ] Who-Is broadcast: discover BACnet devices on the local network."""
    with bacnet_session(target) as net:
        # BAC0.lite exposes Who-Is as ``who_is`` (verified against BAC0/bacpypes3,
        # 2026-06) — broadcasts to the local segment when called with no address.
        raw = list(net.who_is() or [])[:MAX_DEVICES]
        devices = [_norm_device(d) for d in raw]
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "local_interface": s(getattr(target, "host", ""), 48),
        "device_count": len(devices),
        "devices": devices,
        "note": "BACnet Who-Is discovery (read-only). Building/facility devices on "
        "the local BACnet/IP network.",
    }


def bacnet_object_list(target: Any, address: str, device_id: int) -> dict:
    """[READ] Read a device's object list (its BACnet points/objects)."""
    addr = str(address or "").strip()
    dev = _opt_int(device_id)
    if not addr or dev is None:
        return {"error": "address and device_id are required (from bacnet_discover)."}
    with bacnet_session(target) as net:
        raw = net.read(f"{addr} device {dev} objectList")
        objects = [_norm_object(o) for o in list(raw or [])[:MAX_OBJECTS]]
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "address": s(addr, 64),
        "device_id": dev,
        "object_count": len(objects),
        "objects": objects,
    }


def bacnet_read_property(
    target: Any, address: str, object_type: str, instance: int,
    bacnet_property: str = "presentValue",
) -> dict:
    """[READ] Read one property of one BACnet object (default presentValue)."""
    addr = str(address or "").strip()
    otype = str(object_type or "").strip()
    inst = _opt_int(instance)
    prop = str(bacnet_property or "presentValue").strip()
    if not addr or not otype or inst is None:
        return {"error": "address, object_type and instance are required."}
    with bacnet_session(target) as net:
        value = net.read(f"{addr} {otype} {inst} {prop}")
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "address": s(addr, 64),
        "object_type": s(otype, 32),
        "instance": inst,
        "property": s(prop, 48),
        "value": num(value) if num(value) is not None else s(value, 200),
    }


def bacnet_read_points(target: Any, address: str, device_id: int) -> dict:
    """[READ] Read presentValue of all monitor-relevant points of a device.

    Reads the device's object list, filters to analog/binary/multistate I/O/value
    objects, and reads each one's presentValue (bounded) — the HVAC/facility
    snapshot. Each point degrades to an error string rather than failing the sweep.
    """
    addr = str(address or "").strip()
    dev = _opt_int(device_id)
    if not addr or dev is None:
        return {"error": "address and device_id are required (from bacnet_discover)."}
    with bacnet_session(target) as net:
        raw = net.read(f"{addr} device {dev} objectList")
        objects = [_norm_object(o) for o in list(raw or [])[:MAX_OBJECTS]]
        readable = [o for o in objects if o["object_type"] in READABLE_TYPES][:MAX_POINT_READS]
        points = []
        for o in readable:
            ref = f"{o['object_type']} {o['instance']}"
            try:
                value = net.read(f"{addr} {ref} presentValue")
                points.append({
                    "object_type": o["object_type"], "instance": o["instance"],
                    "present_value": num(value) if num(value) is not None else s(value, 120),
                })
            except Exception as exc:  # noqa: BLE001 — a per-point miss is data, not fatal
                points.append({"object_type": o["object_type"], "instance": o["instance"],
                               "error": s(str(exc), 120)})
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "address": s(addr, 64),
        "device_id": dev,
        "point_count": len(points),
        "skipped_non_readable": len(objects) - len(readable),
        "points": points,
        "note": "presentValue of analog/binary/multistate points (read-only). "
        "Building/HVAC monitoring snapshot.",
    }


__all__ = [
    "bacnet_discover",
    "bacnet_object_list",
    "bacnet_read_property",
    "bacnet_read_points",
    "OTConnectionError",
]
