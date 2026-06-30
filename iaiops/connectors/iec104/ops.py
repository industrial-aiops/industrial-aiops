"""IEC 60870-5-104 operations — read-only telemetry tap (via the ``c104`` extra).

IEC 60870-5-104 is the TCP profile of IEC 60870-5 telecontrol — the workhorse of
electrical substations / SCADA RTUs in the energy sector. This connector is
**read-only monitoring**: connection status, general interrogation (read all
monitored points of a station/ASDU), and single-point reads. Control direction
commands (C_SC/C_DC/C_RC/setpoints) are OT-dangerous and intentionally NOT exposed
in this preview.

``c104`` (iec104-python) is an OPTIONAL extra imported lazily in
:func:`iaiops.core.runtime.connection._build_iec104_client`. The exact binding
surface is documented there and is 待核实 (unverified against a live RTU) — the
ops below duck-type the client/connection/station/point objects so they survive
minor API differences and are fully mock-testable.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.runtime.connection import OTConnectionError, iec104_session

MAX_POINTS = 5000  # bounded interrogation result


def _enum_name(value: Any) -> str:
    """Render a c104 enum (Type/Quality) or scalar as a bounded string."""
    name = getattr(value, "name", None)
    return s(name if name is not None else value, 48)


def _point_brief(point: Any) -> dict:
    """Normalize one c104 point to a JSON-safe monitored-value descriptor."""
    raw = getattr(point, "value", None)
    return {
        "io_address": _opt_int(getattr(point, "io_address", getattr(point, "address", None))),
        "type": _enum_name(getattr(point, "type", "")),
        "value": num(raw) if num(raw) is not None else s(raw, 64),
        "quality": _enum_name(getattr(point, "quality", "")),
        "recorded_at": s(getattr(point, "recorded_at", getattr(point, "updated_at", "")), 40),
    }


def _opt_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stations(conn: Any) -> list[Any]:
    """Return the connection's stations (bounded), tolerant of attr vs getter."""
    stations = getattr(conn, "stations", None)
    if stations is None:
        getter = getattr(conn, "get_stations", None)
        stations = getter() if callable(getter) else []
    return list(stations or [])


def _station_ca(station: Any) -> int | None:
    return _opt_int(getattr(station, "common_address", getattr(station, "ca", None)))


def iec104_connection_info(target: Any) -> dict:
    """[READ] Connect and report link status + the discovered stations (ASDU CAs)."""
    with iec104_session(target) as (_client, conn):
        stations = _stations(conn)
        cas = [ca for ca in (_station_ca(st) for st in stations) if ca is not None]
        connected = bool(getattr(conn, "is_connected", True))
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "host": s(getattr(target, "host", ""), 40),
        "port": int(getattr(target, "port", 0) or 2404),
        "connected": connected,
        "configured_common_address": int(getattr(target, "common_address", 0) or 0),
        "station_count": len(cas),
        "common_addresses": cas,
        "note": "IEC 60870-5-104 read-only link check. Control commands are not "
        "exposed in this preview.",
    }


def iec104_interrogate(target: Any, common_address: int | None = None) -> dict:
    """[READ] General interrogation: all monitored points of a station (ASDU CA).

    ``common_address`` selects the station; omitted → the endpoint's configured CA,
    else the first discovered station.
    """
    want = common_address if common_address is not None else (
        getattr(target, "common_address", 0) or None
    )
    with iec104_session(target) as (_client, conn):
        station = _pick_station(_stations(conn), want)
        if station is None:
            return {
                "endpoint": s(getattr(target, "name", ""), 64),
                "error": f"No station with common_address={want} found on this link.",
            }
        points = list(getattr(station, "points", []) or [])[:MAX_POINTS]
        rows = [_point_brief(p) for p in points]
        ca = _station_ca(station)
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "common_address": ca,
        "point_count": len(rows),
        "points": rows,
        "note": "General-interrogation snapshot (monitor direction). Values reflect "
        "the RTU's last reported state.",
    }


def iec104_read_point(target: Any, io_address: int, common_address: int | None = None) -> dict:
    """[READ] Read one monitored point by its information-object address (IOA)."""
    want = common_address if common_address is not None else (
        getattr(target, "common_address", 0) or None
    )
    ioa = _opt_int(io_address)
    with iec104_session(target) as (_client, conn):
        station = _pick_station(_stations(conn), want)
        if station is None:
            return {"endpoint": s(getattr(target, "name", ""), 64),
                    "error": f"No station with common_address={want} found."}
        for p in list(getattr(station, "points", []) or [])[:MAX_POINTS]:
            if _opt_int(getattr(p, "io_address", getattr(p, "address", None))) == ioa:
                return {"endpoint": s(getattr(target, "name", ""), 64),
                        "common_address": _station_ca(station), "found": True,
                        **_point_brief(p)}
    return {"endpoint": s(getattr(target, "name", ""), 64), "found": False,
            "io_address": ioa, "note": "No point with that IOA on the station."}


def _pick_station(stations: list[Any], want: int | None) -> Any | None:
    """Pick the station by CA, or the first if ``want`` is None/absent."""
    if not stations:
        return None
    if want is None:
        return stations[0]
    for st in stations:
        if _station_ca(st) == want:
            return st
    return None


__all__ = [
    "iec104_connection_info",
    "iec104_interrogate",
    "iec104_read_point",
    "OTConnectionError",
]
