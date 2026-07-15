"""Read-only OPC-UA operations (digitalization + problem surfacing).

Each function opens a short-lived ``opcua_session``, reads, and closes it. All
server-returned text is sanitized (``s``). Bounds are enforced everywhere — node
counts, browse depth, and sample windows are all capped so an agent can never
trigger an unbounded walk or an infinite subscription loop.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, opcua_session

# Hard caps to keep every call bounded (defensive against agent over-requests).
MAX_BROWSE_NODES = 500
MAX_BROWSE_DEPTH = 6
MAX_READ_NODES = 100
MAX_SAMPLES = 200
MAX_SAMPLE_SECONDS = 60
MAX_HISTORY_POINTS = 2000
OBJECTS_NODE = "i=85"  # standard OPC-UA Objects folder

# Substrings that suggest a node represents an alarm / condition state.
_ALARM_HINTS = ("alarm", "alert", "fault", "condition", "trip", "fail")


def _node_summary(node: Any) -> dict:
    """Return a compact, sanitized descriptor for an OPC-UA node."""
    try:
        bn = node.read_browse_name().Name
    except Exception:  # noqa: BLE001 — browse name is best-effort
        bn = ""
    try:
        ncls = node.read_node_class().name
    except Exception:  # noqa: BLE001
        ncls = ""
    return {
        "node_id": s(node.nodeid.to_string(), 128),
        "browse_name": s(bn, 128),
        "node_class": s(ncls, 32),
    }


def server_info(target: Any) -> dict:
    """[READ] OPC-UA server status: state, build info, namespaces, start time."""
    with opcua_session(target) as client:
        from asyncua import ua  # session guarantees asyncua is importable here

        namespaces = client.get_namespace_array()
        status_node = client.get_node(ua.ObjectIds.Server_ServerStatus)
        status = status_node.read_value()
        build = status.BuildInfo
        return {
            "endpoint": s(target.endpoint_url, 200),
            "state": int(status.State) if status.State is not None else None,
            "start_time": s(status.StartTime, 64),
            "current_time": s(status.CurrentTime, 64),
            "product_name": s(build.ProductName, 128),
            "manufacturer": s(build.ManufacturerName, 128),
            "software_version": s(build.SoftwareVersion, 64),
            "namespace_count": len(namespaces),
            "namespaces": [s(n, 200) for n in namespaces],
        }


def browse(target: Any, node_id: str = OBJECTS_NODE, depth: int = 2) -> list[dict]:
    """[READ] Browse the node tree from ``node_id`` to a bounded ``depth``.

    Returns a flat list of node descriptors, each with its ``depth`` and
    ``parent`` node id. Capped at MAX_BROWSE_NODES / MAX_BROWSE_DEPTH.
    """
    max_depth = max(0, min(int(depth), MAX_BROWSE_DEPTH))
    out: list[dict] = []
    with opcua_session(target) as client:
        root = client.get_node(node_id)
        _walk(root, parent="", level=0, max_depth=max_depth, out=out)
    return out


def _walk(node: Any, parent: str, level: int, max_depth: int, out: list[dict]) -> None:
    """Depth-first browse, mutating ``out`` until a node/depth cap is hit."""
    if len(out) >= MAX_BROWSE_NODES:
        return
    summary = _node_summary(node)
    summary["parent"] = s(parent, 128)
    summary["depth"] = level
    out.append(summary)
    if level >= max_depth:
        return
    try:
        children = node.get_children()
    except Exception:  # noqa: BLE001 — a node may not be browsable
        return
    for child in children:
        if len(out) >= MAX_BROWSE_NODES:
            return
        _walk(child, parent=node.nodeid.to_string(), level=level + 1, max_depth=max_depth, out=out)


def read_node(target: Any, node_id: str) -> dict:
    """[READ] Read one node: value, datatype, source timestamp, status code."""
    with opcua_session(target) as client:
        return _read_one(client, node_id)


def _read_one(client: Any, node_id: str) -> dict:
    """Read a single node id using an already-connected client."""
    try:
        node = client.get_node(node_id)
        dv = node.read_data_value()
    except Exception as exc:  # noqa: BLE001 — bad node id is a per-node error
        return {"node_id": s(node_id, 128), "error": s(str(exc), 200)}
    variant = dv.Value
    return {
        "node_id": s(node_id, 128),
        "value": _coerce_value(variant.Value),
        "datatype": s(getattr(variant.VariantType, "name", ""), 32),
        "source_timestamp": s(dv.SourceTimestamp, 64),
        "status_code": s(getattr(dv.StatusCode, "name", dv.StatusCode), 64),
        "good": bool(getattr(dv.StatusCode, "is_good", lambda: True)()),
    }


def _coerce_value(value: Any) -> Any:
    """Make an OPC-UA value JSON-safe (scalars pass through; else sanitize)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce_value(v) for v in value][:100]
    return s(value, 256)


def read_many(target: Any, node_ids: list[str]) -> list[dict]:
    """[READ] Batch-read multiple node ids in one session (bounded)."""
    ids = list(node_ids or [])[:MAX_READ_NODES]
    with opcua_session(target) as client:
        return [_read_one(client, nid) for nid in ids]


def subscribe_sample(
    target: Any,
    node_id: str,
    samples: int = 5,
    interval_ms: int = 500,
    timeout_s: int = 30,
) -> dict:
    """[READ] Sample a node a *bounded* number of times, then return.

    Samples the node's value every ``interval_ms`` for at most ``samples``
    readings or ``timeout_s`` seconds (whichever comes first) — never an
    unbounded loop. Returns the collected samples plus the count.
    """
    samples = max(1, min(int(samples), MAX_SAMPLES))
    interval_ms = max(50, int(interval_ms))
    timeout_s = max(1, min(int(timeout_s), MAX_SAMPLE_SECONDS))
    deadline = time.monotonic() + timeout_s
    collected: list[dict] = []
    with opcua_session(target) as client:
        node = client.get_node(node_id)
        for _ in range(samples):
            if time.monotonic() >= deadline:
                break
            try:
                dv = node.read_data_value()
                collected.append(
                    {
                        "value": _coerce_value(dv.Value.Value),
                        "source_timestamp": s(dv.SourceTimestamp, 64),
                        "status_code": s(getattr(dv.StatusCode, "name", dv.StatusCode), 64),
                    }
                )
            except Exception as exc:  # noqa: BLE001 — record per-sample read error
                collected.append({"error": s(str(exc), 200)})
            time.sleep(interval_ms / 1000.0)
    return {
        "node_id": s(node_id, 128),
        "requested_samples": samples,
        "collected": len(collected),
        "interval_ms": interval_ms,
        "samples": collected,
    }


def read_alarms(target: Any, node_id: str = OBJECTS_NODE, depth: int = 4) -> dict:
    """[READ] Best-effort active-condition surfacing via the address space.

    Full OPC-UA Alarms & Conditions (event subscriptions) is not modelled in
    this preview. Instead this browses the tree (bounded) and reports any
    boolean variable whose name suggests an alarm/condition/fault that currently
    reads True. If nothing alarm-like is found, returns a clear note.
    """
    depth = max(1, min(int(depth), MAX_BROWSE_DEPTH))
    active: list[dict] = []
    scanned = 0
    with opcua_session(target) as client:
        root = client.get_node(node_id)
        scanned = _scan_alarms(client, root, depth_left=depth, active=active)
    note = (
        "Browsed boolean nodes whose name suggests an alarm/condition (untimed). "
        "For servers with A&C event support, alarm_events returns the same "
        "conditions WITH the server's event timestamps."
    )
    return {
        "active_alarms": active,
        "active_count": len(active),
        "nodes_scanned": scanned,
        "note": note,
    }


def _scan_alarms(client: Any, node: Any, depth_left: int, active: list[dict]) -> int:
    """Walk the tree counting nodes; collect alarm-like booleans reading True."""
    scanned = 1
    if len(active) >= MAX_BROWSE_NODES or scanned > MAX_BROWSE_NODES:
        return scanned
    try:
        bn = node.read_browse_name().Name or ""
    except Exception:  # noqa: BLE001
        bn = ""
    lowered = bn.lower()
    if any(h in lowered for h in _ALARM_HINTS):
        try:
            value = node.read_value()
            if isinstance(value, bool) and value:
                active.append(
                    {
                        "node_id": s(node.nodeid.to_string(), 128),
                        "browse_name": s(bn, 128),
                        "value": True,
                    }
                )
        except Exception:  # noqa: BLE001 — non-readable node, skip
            pass
    if depth_left <= 0:
        return scanned
    try:
        children = node.get_children()
    except Exception:  # noqa: BLE001
        return scanned
    for child in children:
        if scanned >= MAX_BROWSE_NODES:
            break
        scanned += _scan_alarms(client, child, depth_left - 1, active)
    return scanned


class _AlarmEventBuffer:
    """asyncua subscription handler collecting parsed A&C events (bounded)."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.events: list[dict] = []

    def event_notification(self, event: Any) -> None:
        if len(self.events) >= self.cap:
            return
        self.events.append(_parse_alarm_event(event))


def _localized_text(value: Any) -> str:
    """Extract the text of a LocalizedText-ish value (best-effort)."""
    text = getattr(value, "Text", value)
    return "" if text is None else str(text)


def _parse_alarm_event(event: Any) -> dict:
    """Normalize one A&C event to the RCA/ISA-18.2 alarm-event shape (best-effort)."""
    active_state = getattr(event, "ActiveState", None)
    retain = getattr(event, "Retain", None)
    if active_state is not None:
        active: bool | None = _localized_text(active_state).strip().lower() == "active"
    elif retain is not None:
        active = bool(retain)
    else:
        active = None  # plain event (no condition state) — reported as EVENT
    time_val = getattr(event, "Time", None)
    severity = getattr(event, "Severity", None)
    return {
        "source": s(_localized_text(getattr(event, "SourceName", "")) or "event", 96),
        "message": s(_localized_text(getattr(event, "Message", "")), 200),
        "severity": int(severity) if severity is not None else None,
        "state": "ACTIVE" if active else ("RTN" if active is False else "EVENT"),
        # The SERVER's event Time — the timed alarm feed RCA temporal weighting needs.
        "timestamp": s(time_val.isoformat(), 64) if isinstance(time_val, datetime) else None,
    }


def alarm_events(
    target: Any, duration_s: float = 5.0, refresh: bool = True, max_events: int = 200
) -> dict:
    """[READ] Timestamped Alarms & Conditions via a *bounded* event subscription.

    Subscribes to the Server object for Condition-type events, optionally calls
    ``ConditionRefresh`` so currently-retained conditions are re-announced WITH
    their original event ``Time``, listens for at most ``duration_s`` seconds (or
    ``max_events``), then unsubscribes. This is the timed complement to
    ``read_alarms``' address-space scan: each event carries the server's own
    timestamp, so the RCA copilot can time-localize alarm evidence. Requires a
    server that implements A&C event subscriptions (待核实 per server); on
    servers without it the subscription simply yields nothing — pair with
    ``read_alarms`` as the untimed fallback.
    """
    duration_s = max(0.0, min(float(duration_s), MAX_SAMPLE_SECONDS))
    max_events = max(1, min(int(max_events), MAX_SAMPLES))
    buffer = _AlarmEventBuffer(max_events)
    refreshed = False
    refresh_error = ""
    with opcua_session(target) as client:
        from asyncua import ua  # session guarantees asyncua is importable here

        sub = client.create_subscription(500, buffer)
        try:
            server_node = client.get_node(ua.ObjectIds.Server)
            condition_type = client.get_node(ua.ObjectIds.ConditionType)
            sub.subscribe_events(server_node, condition_type)
            if refresh:
                try:
                    # asyncua's sync Subscription doesn't proxy subscription_id —
                    # it lives on the wrapped aio object (verified against 1.x).
                    sub_id = getattr(sub, "subscription_id", None)
                    if sub_id is None:
                        sub_id = sub.aio_obj.subscription_id
                    condition_type.call_method(
                        ua.NodeId(ua.ObjectIds.ConditionType_ConditionRefresh),
                        ua.Variant(sub_id, ua.VariantType.UInt32),
                    )
                    refreshed = True
                except Exception as exc:  # noqa: BLE001 — refresh support varies per server
                    if "BadNothingToDo" in str(exc):
                        refreshed = True  # refresh ran; the server holds no retained conditions
                    else:
                        refresh_error = s(str(exc), 200)
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline and len(buffer.events) < max_events:
                time.sleep(0.1)
        finally:
            try:
                sub.delete()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
    return {
        "endpoint": s(target.name, 64),
        "duration_s": duration_s,
        "condition_refresh": refreshed,
        "refresh_error": refresh_error,
        "event_count": len(buffer.events),
        "events": buffer.events[:max_events],
        "note": (
            "Events carry the server's own Time (timed alarm evidence). An empty "
            "result can mean either no events in the window or a server without "
            "A&C event support — read_alarms is the untimed fallback."
        ),
    }


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerant of a trailing Z), else None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def read_history(
    target: Any,
    node_id: str,
    start: str | None = None,
    end: str | None = None,
    max_points: int = 1000,
) -> dict:
    """[READ] OPC-UA Historical Access (HDA): raw values over a [start,end] window.

    Reads stored historical values for a node via the server's HistoryRead
    service (asyncua ``read_raw_history``), bounded by ``max_points``. ``start`` /
    ``end`` are ISO-8601; defaults to the last hour. Returns a clear message when
    the server does not support history for the node.
    """
    max_points = max(1, min(int(max_points), MAX_HISTORY_POINTS))
    end_dt = _parse_iso(end) or datetime.now()  # noqa: DTZ005 — server-local window
    start_dt = _parse_iso(start) or (end_dt - timedelta(hours=1))
    with opcua_session(target) as client:
        node = client.get_node(node_id)
        try:
            values = node.read_raw_history(start_dt, end_dt, numvalues=max_points)
        except Exception as exc:  # noqa: BLE001 — many servers lack HDA for a node
            return {
                "node_id": s(node_id, 128),
                "supported": False,
                "values": [],
                "count": 0,
                "note": s(
                    "Server returned no history for this node (HDA may be "
                    f"unsupported or the node is not historized): {exc}",
                    240,
                ),
            }
        out = []
        for dv in list(values)[:max_points]:
            out.append(
                {
                    "value": _coerce_value(getattr(dv.Value, "Value", None)),
                    "source_timestamp": s(dv.SourceTimestamp, 64),
                    "status_code": s(getattr(dv.StatusCode, "name", dv.StatusCode), 64),
                }
            )
    return {
        "node_id": s(node_id, 128),
        "supported": True,
        "start": s(start_dt, 64),
        "end": s(end_dt, 64),
        "count": len(out),
        "values": out,
    }


def read_value_or_error(client: Any, node_id: str) -> tuple[float | None, dict]:
    """Helper used by analysis: read a node's numeric value + its descriptor.

    Returns ``(numeric_value_or_None, raw_descriptor)``. Raising is reserved for
    connection failures (handled by the caller's session); a bad node id yields
    an error descriptor, not an exception.
    """
    from iaiops.core.brain._shared import num

    desc = _read_one(client, node_id)
    if "error" in desc:
        return None, desc
    return num(desc.get("value")), desc


__all__ = [
    "server_info",
    "browse",
    "read_node",
    "read_many",
    "subscribe_sample",
    "read_alarms",
    "alarm_events",
    "read_history",
    "opcua_session",
    "OTConnectionError",
    "read_value_or_error",
    "MAX_SAMPLES",
]
