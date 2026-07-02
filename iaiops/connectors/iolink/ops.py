"""IO-Link operations (read-only, sensor-level visibility via an IO-Link master).

IO-Link (IEC 61131-9) devices hang off an IO-Link *master*; modern masters
(ifm, Balluff, Turck, ...) expose an HTTP/JSON read surface — the IO-Link
consortium "JSON Integration" / ifm IoT-Core datapoint tree:

* master identity      — ``/deviceinfo/<field>/getdata``
* per-port device      — ``/iolinkmaster/port[N]/iolinkdevice/<field>/getdata``
* process data in      — ``/iolinkmaster/port[N]/iolinkdevice/pdin/getdata`` (hex)
* ISDU parameter read  — ``/iolinkmaster/port[N]/iolinkdevice/iolreadacyclic``
  with ``{"index": ..., "subindex": ...}``

Datapoint paths follow the ifm IoT-Core tree; other vendors' exact prefixes are
待核实 (the in-repo mock master in ``tests/test_iolink.py`` is the self-test).
v1 is strictly READ-ONLY: no setdata/write services are exposed anywhere.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s

MAX_PORTS = 32
DEFAULT_PORT_COUNT = 8
MAX_ISDU_INDEX = 0xFFFF
MAX_ISDU_SUBINDEX = 0xFF

# Master identity datapoints (ifm IoT-Core names; other vendors 待核实).
_MASTER_FIELDS = ("productcode", "serialnumber", "hwrevision", "swrevision")
# Connected-device identity datapoints per the JSON integration tree.
_DEVICE_FIELDS = ("vendorid", "deviceid", "productname", "serial", "status")


def _session(target: Any):
    """The assembled ``iolink_session`` (late import: connection imports our transport)."""
    from iaiops.core.runtime.connection import iolink_session

    return iolink_session(target)


def _check_port(port: int) -> int:
    """Validate an IO-Link master port number (1..MAX_PORTS)."""
    port = int(port)
    if not 1 <= port <= MAX_PORTS:
        raise ValueError(f"IO-Link port must be 1..{MAX_PORTS}, got {port}.")
    return port


def _try_read(client: Any, adr: str) -> tuple[Any, str]:
    """Read one datapoint, returning (value, "") or (None, error).

    Only ``ValueError`` (a master rejection/garbage for THIS datapoint) is
    tolerated — transport failures (dead master, timeout) propagate so the
    session translates them into a teaching ``OTConnectionError``.
    """
    try:
        return client.request(adr), ""
    except ValueError as exc:  # per-datapoint miss is data, not a crash
        return None, s(str(exc), 160)


def master_info(target: Any) -> dict:
    """[READ] IO-Link master identity from the /deviceinfo tree."""
    with _session(target) as client:
        info: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for field in _MASTER_FIELDS:
            value, err = _try_read(client, f"/deviceinfo/{field}/getdata")
            if err:
                errors[field] = err
            else:
                info[field] = s(value, 96) if isinstance(value, str) else value
        out = {
            "endpoint": s(target.name, 64),
            "flavor": client.flavor,
            "master": info,
        }
        if errors:
            out["unavailable"] = errors  # datapoints this master doesn't expose
        return out


def _port_entry(client: Any, port: int) -> dict:
    """One port's mode/status + connected-device identity (never raises)."""
    entry: dict[str, Any] = {"port": port}
    mode, mode_err = _try_read(client, f"/iolinkmaster/port[{port}]/mode/getdata")
    if mode_err:
        return {"port": port, "present": False, "error": mode_err}
    entry["present"] = True
    entry["mode"] = mode
    status, status_err = _try_read(
        client, f"/iolinkmaster/port[{port}]/iolinkdevice/status/getdata"
    )
    if status_err:
        entry["device_connected"] = False
        return entry
    entry["device_connected"] = True
    entry["device_status"] = status
    for field in ("vendorid", "deviceid", "productname"):
        value, err = _try_read(client, f"/iolinkmaster/port[{port}]/iolinkdevice/{field}/getdata")
        if not err:
            entry[field] = s(value, 96) if isinstance(value, str) else value
    return entry


def ports(target: Any, count: int = DEFAULT_PORT_COUNT) -> dict:
    """[READ] BOUNDED port sweep: mode/status + connected device identity per port."""
    count = max(1, min(int(count), MAX_PORTS))
    with _session(target) as client:
        entries = [_port_entry(client, n) for n in range(1, count + 1)]
    present = [e for e in entries if e.get("present")]
    return {
        "endpoint": s(target.name, 64),
        "ports_checked": count,
        "ports_present": len(present),
        "devices_connected": sum(1 for e in present if e.get("device_connected")),
        "ports": entries,
    }


def device_info(target: Any, port: int) -> dict:
    """[READ] Identity of the IO-Link device on one port (vendor/device/serial/status)."""
    port = _check_port(port)
    with _session(target) as client:
        device: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for field in _DEVICE_FIELDS:
            value, err = _try_read(
                client, f"/iolinkmaster/port[{port}]/iolinkdevice/{field}/getdata"
            )
            if err:
                errors[field] = err
            else:
                device[field] = s(value, 96) if isinstance(value, str) else value
        out = {"endpoint": s(target.name, 64), "port": port, "device": device}
        if errors:
            out["unavailable"] = errors
        return out


def read_pdin(target: Any, port: int) -> dict:
    """[READ] Process-data-in of one port: raw hex string + decoded byte array."""
    port = _check_port(port)
    with _session(target) as client:
        raw = client.request(f"/iolinkmaster/port[{port}]/iolinkdevice/pdin/getdata")
    hex_str = str(raw).strip()
    try:
        data = bytes.fromhex(hex_str)
    except ValueError as exc:
        raise ValueError(
            f"IO-Link port {port} pdin is not a hex string: {s(hex_str, 64)!r} "
            f"({exc}). This master may encode pdin differently (待核实)."
        ) from exc
    return {
        "endpoint": s(target.name, 64),
        "port": port,
        "pdin_hex": s(hex_str, 512),
        "bytes": list(data),
        "byte_count": len(data),
        "note": "Decode per the device's IODD (process data layout is device-specific).",
    }


def read_isdu(target: Any, port: int, index: int, subindex: int = 0) -> dict:
    """[READ] ISDU acyclic parameter read (iolreadacyclic) — bounded index/subindex."""
    port = _check_port(port)
    index = int(index)
    subindex = int(subindex)
    if not 0 <= index <= MAX_ISDU_INDEX:
        raise ValueError(f"ISDU index must be 0..{MAX_ISDU_INDEX}, got {index}.")
    if not 0 <= subindex <= MAX_ISDU_SUBINDEX:
        raise ValueError(f"ISDU subindex must be 0..{MAX_ISDU_SUBINDEX}, got {subindex}.")
    with _session(target) as client:
        value = client.request(
            f"/iolinkmaster/port[{port}]/iolinkdevice/iolreadacyclic",
            data={"index": index, "subindex": subindex},
        )
    return {
        "endpoint": s(target.name, 64),
        "port": port,
        "index": index,
        "subindex": subindex,
        # Typically a hex string of the parameter octets (master-dependent 待核实).
        "value": s(value, 512) if isinstance(value, str) else value,
    }


def scan(target: Any, count: int = DEFAULT_PORT_COUNT) -> dict:
    """[READ] One-shot bounded snapshot: master identity + every port's state."""
    count = max(1, min(int(count), MAX_PORTS))
    with _session(target) as client:
        info: dict[str, Any] = {}
        for field in _MASTER_FIELDS:
            value, err = _try_read(client, f"/deviceinfo/{field}/getdata")
            if not err:
                info[field] = s(value, 96) if isinstance(value, str) else value
        entries = [_port_entry(client, n) for n in range(1, count + 1)]
    present = [e for e in entries if e.get("present")]
    return {
        "endpoint": s(target.name, 64),
        "flavor": client.flavor,
        "master": info,
        "ports_checked": count,
        "ports_present": len(present),
        "devices_connected": sum(1 for e in present if e.get("device_connected")),
        "ports": entries,
    }


__all__ = [
    "DEFAULT_PORT_COUNT",
    "MAX_ISDU_INDEX",
    "MAX_ISDU_SUBINDEX",
    "MAX_PORTS",
    "device_info",
    "master_info",
    "ports",
    "read_isdu",
    "read_pdin",
    "scan",
]
