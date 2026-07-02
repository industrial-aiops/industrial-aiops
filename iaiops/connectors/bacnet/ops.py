"""BACnet/IP operations — read-only facility / HVAC monitoring (via the ``bacnet`` extra).

BACnet/IP (ASHRAE 135) is the dominant building-automation protocol — HVAC,
lighting, metering, 厂务/facility plant. This connector is read-first: device
discovery (Who-Is), object-list browse, and property reads (present-value of
analog/binary/multistate points). Property writes (present-value with priority /
relinquish) ARE exposed via :func:`bacnet_write_property` — an OT-DANGEROUS write
for live building control: it is governed (high risk_tier), captures the BEFORE
value for undo, and must run through dry-run + double-confirm.

``BAC0`` (over bacpypes3) is an OPTIONAL extra imported lazily in
:func:`iaiops.core.runtime.connection._build_bacnet_network`. The BAC0 surface is
duck-typed and 待核实 (unverified against live gear) — the ops below build BACnet
request strings and normalize results defensively, and are fully mock-testable.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.runtime.connection import OTConnectionError, bacnet_session

MAX_DEVICES = 2000
MAX_OBJECTS = 2000
MAX_POINT_READS = 500

# COV (change-of-value) capture bounds — the capture is ALWAYS bounded by BOTH a
# notification count and a wall-clock timeout, and the subscription is always
# cancelled. It can never become an open subscription loop.
MAX_COV_NOTIFICATIONS = 500
MAX_COV_TIMEOUT_S = 300
MAX_COV_LIFETIME_S = 3600
_COV_POLL_S = 0.05

# TrendLog read bound — a single bounded ReadRange of the device's log buffer.
MAX_TREND_RECORDS = 1000

# Monitor-relevant object types whose presentValue is worth a bulk read.
READABLE_TYPES = (
    "analogInput", "analogOutput", "analogValue",
    "binaryInput", "binaryOutput", "binaryValue",
    "multiStateInput", "multiStateOutput", "multiStateValue",
)


def _device_id_from_identifier(ident: Any) -> int | None:
    """Extract the device instance from a BACnet object identifier.

    bacpypes3 renders a device identifier as ``('device', 599)`` (tuple-like) or
    the text ``device,599`` — the instance is the trailing integer either way.
    """
    if isinstance(ident, (list, tuple)) and len(ident) >= 2:
        return _opt_int(ident[1])
    inst = getattr(ident, "instance", None)
    if inst is not None:
        return _opt_int(inst)
    text = str(ident)
    for sep in (",", ":", " "):
        if sep in text:
            return _opt_int(text.rsplit(sep, 1)[-1])
    return _opt_int(text)


def _norm_device(item: Any) -> dict:
    """Normalize a BAC0 who_is result to ``{device_id, address}``.

    Modern BAC0 (async, over bacpypes3) returns ``IAmRequest`` APDU objects — the
    device is ``iAmDeviceIdentifier`` and the responder is ``pduSource`` (verified
    live against bacpypes3 0.0.106, 2026-07). Sync-era BAC0 and test doubles use a
    ``(device_id, address)`` tuple or a ``.device_id``/``.address`` object; all
    three shapes are handled.
    """
    # bacpypes3 IAmRequest (modern BAC0 who_is) — check first: it is the live shape.
    ident = getattr(item, "iAmDeviceIdentifier", None)
    if ident is not None:
        return {
            "device_id": _device_id_from_identifier(ident),
            "address": s(getattr(item, "pduSource", None), 64),
        }
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


def _camel_object_type(text: str) -> str:
    """Normalize a BACnet object type to the camelCase form the ops use.

    bacpypes3 renders object types kebab-cased (``analog-value``,
    ``multi-state-value``); the connector's public shape — and ``READABLE_TYPES``
    — is camelCase (``analogValue``, ``multiStateValue``). Converting here keeps a
    single consistent object-type vocabulary regardless of the BAC0 build, and is
    idempotent for input that is already camelCase (no dash → unchanged).
    """
    if "-" not in text:
        return text
    head, *rest = text.split("-")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _norm_object(item: Any) -> dict:
    """Normalize an object-list entry (objectType, instance) tuple/obj."""
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return {"object_type": _camel_object_type(s(item[0], 32)), "instance": _opt_int(item[1])}
    raw_type = s(getattr(item, "objectType", getattr(item, "object_type", "")), 32)
    return {
        "object_type": _camel_object_type(raw_type),
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


def _cov_task_ids(net: Any) -> set:
    """Snapshot the network's live COV task ids (BAC0 keys ``cov_tasks`` by id)."""
    tasks = getattr(net, "cov_tasks", None)
    try:
        return set(tasks or {})
    except TypeError:  # pragma: no cover — defensive: non-iterable cov_tasks
        return set()


def bacnet_cov_subscribe(
    target: Any, address: str, object_type: str, instance: int,
    max_notifications: int = 20, timeout_s: int = 30, lifetime_s: int = 300,
) -> dict:
    """[READ] Bounded Change-of-Value capture for one BACnet object.

    Subscribes to the object's COV (the device pushes a notification whenever the
    point changes), collects up to ``max_notifications`` notifications OR until
    ``timeout_s`` elapses — whichever comes first — then ALWAYS unsubscribes and
    returns the captured changes. This is never an open subscription: both the
    count and the wall-clock are hard-capped, and the subscription is cancelled in
    a ``finally`` so it cannot leak on the device.
    """
    addr = str(address or "").strip()
    otype = str(object_type or "").strip()
    inst = _opt_int(instance)
    if not addr or not otype or inst is None:
        return {"error": "address, object_type and instance are required."}
    cap = max(1, min(int(max_notifications), MAX_COV_NOTIFICATIONS))
    timeout = max(1, min(int(timeout_s), MAX_COV_TIMEOUT_S))
    lifetime = max(1, min(int(lifetime_s), MAX_COV_LIFETIME_S))

    changes: list[dict] = []
    lock = threading.Lock()

    def _collect(prop_id: Any, value: Any) -> None:
        # Called from BAC0's asyncio thread on each notification — append under a
        # lock so the bounded wait loop reads a consistent count.
        with lock:
            if len(changes) >= cap:
                return
            changes.append({
                "property": s(prop_id, 48),
                "value": num(value) if num(value) is not None else s(value, 120),
                "wall_clock": datetime.now(tz=UTC).isoformat(timespec="milliseconds"),
            })

    with bacnet_session(target) as net:
        before = _cov_task_ids(net)
        # BAC0.lite.cov(address, objectID=(type, inst), lifetime, confirmed, callback)
        # — verified against BAC0/bacpypes3 (2026-06). The callback receives
        # (property_identifier, property_value).
        net.cov(addr, objectID=(otype, inst), lifetime=lifetime,
                confirmed=False, callback=_collect)
        new_ids = _cov_task_ids(net) - before
        try:
            deadline = time.monotonic() + timeout
            reason = "timeout"
            while time.monotonic() < deadline:
                with lock:
                    if len(changes) >= cap:
                        reason = "max_notifications"
                        break
                time.sleep(_COV_POLL_S)
        finally:
            # Always unsubscribe every task this capture created (BAC0.cancel_cov).
            for task_id in new_ids:
                try:
                    net.cancel_cov(task_id)
                except Exception:  # noqa: BLE001 — cancel must not mask the result
                    pass
        with lock:
            captured = list(changes)
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "address": s(addr, 64),
        "object_type": s(otype, 32),
        "instance": inst,
        "requested_max": cap,
        "timeout_s": timeout,
        "lifetime_s": lifetime,
        "notification_count": len(captured),
        "terminated_reason": reason,
        "changes": captured,
        "note": "Bounded COV capture (read-only): up to requested_max notifications "
        "or timeout_s, then unsubscribed. Never an open subscription.",
    }


def _record_timestamp(record: Any) -> str:
    """Normalize a TrendLog record timestamp (bacpypes3 DateTime: .date/.time)."""
    ts = getattr(record, "timestamp", None)
    if ts is None:
        return ""
    date = getattr(ts, "date", None)
    tval = getattr(ts, "time", None)
    if date is not None and tval is not None:
        return s(f"{date} {tval}", 64)
    return s(ts, 64)


# logDatum is a CHOICE — probe the common value members in priority order.
_LOG_DATUM_MEMBERS = (
    "realValue", "enumValue", "unsignedValue", "signedValue",
    "booleanValue", "bitstringValue", "anyValue",
)


def _record_value(record: Any) -> Any:
    """Extract the value from a TrendLog record's logDatum CHOICE, defensively."""
    datum = getattr(record, "logDatum", record)
    for member in _LOG_DATUM_MEMBERS:
        val = getattr(datum, member, None)
        if val is not None:
            return num(val) if num(val) is not None else s(val, 120)
    return num(datum) if num(datum) is not None else s(datum, 120)


def bacnet_read_trend_log(
    target: Any, address: str, instance: int,
    count: int = 100, newest_first: bool = True,
) -> dict:
    """[READ] Read buffered records from a device's BACnet TrendLog object.

    A TrendLog object logs a point's value over time on the device itself; this
    reads its ``logBuffer`` with a single bounded ReadRange (RangeByPosition).
    ``count`` is hard-capped; ``newest_first`` reverses the search so the most
    recent records come first. Read-only historical trend — no device state changes.
    """
    addr = str(address or "").strip()
    inst = _opt_int(instance)
    if not addr or inst is None:
        return {"error": "address and instance are required (the TrendLog instance)."}
    want = max(1, min(int(count), MAX_TREND_RECORDS))
    # RangeByPosition tuple: (range_type, first, date, time, count). A negative
    # count walks backwards from the end → newest records first (BAC0/bacpypes3).
    range_count = -want if newest_first else want
    range_params = ("p", 1, None, None, range_count)
    request = f"{addr} trendLog {inst} logBuffer"
    with bacnet_session(target) as net:
        # BAC0.lite.readRange(args, range_params=...) — verified against
        # BAC0/bacpypes3 (2026-06); returns a list of log records.
        raw = net.readRange(request, range_params=range_params)
        records = [
            {"timestamp": _record_timestamp(r), "value": _record_value(r)}
            for r in list(raw or [])[:MAX_TREND_RECORDS]
        ]
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "address": s(addr, 64),
        "instance": inst,
        "requested_count": want,
        "newest_first": bool(newest_first),
        "record_count": len(records),
        "records": records,
        "note": "Buffered BACnet TrendLog records (read-only historical trend), "
        "bounded by requested_count.",
    }


def _shown_value(value: Any, relinquish: bool) -> Any:
    """JSON-safe display of a value to write ('null' when relinquishing priority)."""
    if relinquish:
        return "null"
    return num(value) if num(value) is not None else s(value, 120)


def bacnet_write_property(
    target: Any,
    address: str,
    object_type: str,
    instance: int,
    value: Any,
    priority: int | None = None,
    bacnet_property: str = "presentValue",
    relinquish: bool = False,
    *,
    dry_run: bool = True,
) -> dict:
    """[WRITE][HIGH RISK] Write one property of one BACnet object (off by default).

    OT-dangerous — overriding a live building-control point (present-value, optionally
    at a BACnet priority, or relinquishing that priority) can move real HVAC/plant.
    Captures the BEFORE value (read-back) so the change is reversible, and refuses to
    act unless ``dry_run`` is explicitly False. 未经授权勿对生产控制系统写入.
    """
    addr = str(address or "").strip()
    otype = str(object_type or "").strip()
    inst = _opt_int(instance)
    prop = str(bacnet_property or "presentValue").strip()
    if not addr or not otype or inst is None:
        return {"error": "address, object_type and instance are required."}
    prio = _opt_int(priority)
    request = f"{addr} {otype} {inst} {prop} {'null' if relinquish else value}"
    if prio is not None:
        request += f" - {prio}"
    shown = _shown_value(value, relinquish)
    with bacnet_session(target) as net:
        try:
            raw_before = net.read(f"{addr} {otype} {inst} {prop}")
            before = num(raw_before) if num(raw_before) is not None else s(raw_before, 200)
            read_error = ""
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = None
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "endpoint": s(getattr(target, "name", ""), 64),
                "address": s(addr, 64),
                "object_type": s(otype, 32),
                "instance": inst,
                "property": s(prop, 48),
                "priority": prio,
                "relinquish": bool(relinquish),
                "dry_run": True,
                "before": before,
                "would_write": shown,
                "request": s(request, 200),
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        net.write(request)
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "address": s(addr, 64),
        "object_type": s(otype, 32),
        "instance": inst,
        "property": s(prop, 48),
        "priority": prio,
        "relinquish": bool(relinquish),
        "dry_run": False,
        "before": before,
        "written": shown,
        "applied": True,
    }


__all__ = [
    "bacnet_discover",
    "bacnet_object_list",
    "bacnet_read_property",
    "bacnet_read_points",
    "bacnet_cov_subscribe",
    "bacnet_read_trend_log",
    "bacnet_write_property",
    "OTConnectionError",
]
