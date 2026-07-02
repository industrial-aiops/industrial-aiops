"""PROFINET operations — DCP discovery / identify / asset (read-only, via pnio-dcp).

PROFINET-DCP (Discovery and Configuration Protocol) is a **layer-2** broadcast
protocol: one IdentifyAll on the local segment surfaces *every* PROFINET station
(name-of-station, MAC, IP, vendor/device id, role) without connecting to any of
them — closer to passive discovery than the active per-device fingerprint other
connectors use. ``pnio-dcp`` is an OPTIONAL extra (``pip install iaiops[profinet]``)
imported LAZILY in :func:`iaiops.core.runtime.connection._build_profinet_dcp`.

SCOPE (deliberate): read-only discovery + identify, PLUS one MOC-gated DCP *Set*
write. We do NOT do RT cyclic process data (that needs an IO-controller/IO-device
stack and hard real-time, which is out of scope and unsafe to tap). The DCP *Set*
services for name-of-station / IP suite ARE exposed via :func:`profinet_dcp_set` —
an OT-DANGEROUS write that re-addresses a live device: it is governed (high
risk_tier), captures the BEFORE addressing for undo, and must run through dry-run +
double-confirm. Blink / factory-reset remain out of scope (physical/destructive).

HARD REQUIREMENTS: raw-socket access (root / admin / CAP_NET_RAW) on the NIC
cabled to the PROFINET subnet; ``host`` is THIS machine's IP on that subnet. No
universal software simulator — validate against a real device or a DCP simulator.
Every tool degrades to a teaching ``OTConnectionError`` → sanitized error dict
rather than crashing.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, profinet_dcp

MAX_STATIONS = 1024  # bounded enumeration (defensive against a huge/spoofed segment)

# PROFINET DCP device-role bitmask (ERTEC / GSDML): a device may be several roles.
_ROLE_BITS = ((0x01, "io_device"), (0x02, "io_controller"),
              (0x04, "io_multidevice"), (0x08, "io_supervisor"))


def _decode_roles(value: Any) -> list[str]:
    """Decode a DCP device-role bitmask into human role names (best-effort)."""
    try:
        code = int(value)
    except (TypeError, ValueError):
        return []
    return [name for bit, name in _ROLE_BITS if code & bit]


def _device_brief(dev: Any) -> dict:
    """Normalize one pnio-dcp device descriptor to a JSON-safe identity dict.

    pnio-dcp's device object exposes name_of_station / MAC / IP / netmask /
    gateway; vendor/device id and role are surfaced best-effort (their presence
    depends on what the station returned in its IdentifyAll response).
    """
    role_raw = _first_attr(dev, "device_role", "role")
    return {
        "name_of_station": s(_first_attr(dev, "name_of_station", "name_of_station_"), 240),
        "mac": s(_first_attr(dev, "MAC", "mac"), 24),
        "ip": s(_first_attr(dev, "IP", "ip"), 40),
        "netmask": s(_first_attr(dev, "netmask", "subnet"), 40),
        "gateway": s(_first_attr(dev, "gateway", "gw"), 40),
        "vendor_id": _opt_int(_first_attr(dev, "vendor_id", "vendorID")),
        "device_id": _opt_int(_first_attr(dev, "device_id", "deviceID")),
        "device_role_raw": _opt_int(role_raw),
        "device_roles": _decode_roles(role_raw),
        "device_family": s(_first_attr(dev, "family", "device_family", "vendor_name"), 96),
    }


def _first_attr(obj: Any, *names: str) -> Any:
    """Return the first present, non-empty attribute among ``names`` (else "")."""
    for n in names:
        val = getattr(obj, n, None)
        if val not in (None, ""):
            return val
    return ""


def _opt_int(value: Any) -> int | None:
    """Coerce a DCP numeric field to int, else None (absent in some responses)."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def profinet_discover(target: Any) -> dict:
    """[READ] DCP IdentifyAll: every PROFINET station on the local segment.

    One layer-2 broadcast; returns each station's identity. No per-device
    connection is made — this is segment-wide discovery, not a targeted probe.
    """
    with profinet_dcp(target) as dcp:
        devices = list(dcp.identify_all() or [])[:MAX_STATIONS]
        stations = [_device_brief(d) for d in devices]
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "local_ip": s(getattr(target, "host", "") or getattr(target, "nic", ""), 40),
        "station_count": len(stations),
        "stations": stations,
        "note": "DCP IdentifyAll broadcast on the local layer-2 segment. Read-only "
        "discovery — no connection per device, no RT cyclic data. Fields present "
        "depend on each station's IdentifyAll response.",
    }


def profinet_identify_station(target: Any, name_of_station: str) -> dict:
    """[READ] Identify the station whose name-of-station matches (DCP IdentifyAll).

    PROFINET stations are addressed by their name-of-station; this filters the
    IdentifyAll result for an exact (case-insensitive) name match.
    """
    wanted = str(name_of_station or "").strip().lower()
    if not wanted:
        return {"error": "name_of_station is required (the PROFINET station name)."}
    with profinet_dcp(target) as dcp:
        devices = list(dcp.identify_all() or [])[:MAX_STATIONS]
        for d in devices:
            brief = _device_brief(d)
            if brief["name_of_station"].strip().lower() == wanted:
                return {"endpoint": s(getattr(target, "name", ""), 64), "found": True, **brief}
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "found": False,
        "name_of_station": s(name_of_station, 240),
        "note": "No station with that name-of-station answered IdentifyAll on this "
        "segment. Check the spelling, that the device is powered, and that you are "
        "on the right NIC/subnet.",
    }


def profinet_station_params(target: Any, mac: str) -> dict:
    """[READ] Targeted DCP Get for one station (by MAC): name + IP suite.

    A unicast DCP Get to a single station — name-of-station, IP, netmask, gateway —
    useful to re-read one device's addressing without a full broadcast. Uses the
    library's get-by-MAC helpers when available, else falls back to filtering
    IdentifyAll by MAC.
    """
    wanted = str(mac or "").strip().lower()
    if not wanted:
        return {"error": "mac is required (the station's MAC, e.g. '00:11:22:33:44:55')."}
    with profinet_dcp(target) as dcp:
        direct = _get_by_mac(dcp, mac)
        if direct is not None:
            return {"endpoint": s(getattr(target, "name", ""), 64), "mac": s(mac, 24), **direct}
        for d in list(dcp.identify_all() or [])[:MAX_STATIONS]:
            brief = _device_brief(d)
            if brief["mac"].strip().lower() == wanted:
                return {"endpoint": s(getattr(target, "name", ""), 64), "found": True, **brief}
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "found": False,
        "mac": s(mac, 24),
        "note": "No station with that MAC answered on this segment.",
    }


def _get_by_mac(dcp: Any, mac: str) -> dict | None:
    """Best-effort unicast DCP Get via pnio-dcp helpers; None if unsupported."""
    get_name = getattr(dcp, "get_name_of_station", None)
    get_ip = getattr(dcp, "get_ip_address", None)
    if not callable(get_name) and not callable(get_ip):
        return None
    out: dict = {"found": True}
    try:
        if callable(get_name):
            out["name_of_station"] = s(get_name(mac), 240)
        if callable(get_ip):
            ip = get_ip(mac)
            # Some versions return an IPParameter with ip/netmask/gateway fields.
            out["ip"] = s(_first_attr(ip, "ip", "IP") or ip, 40)
            out["netmask"] = s(_first_attr(ip, "netmask", "subnet"), 40)
            out["gateway"] = s(_first_attr(ip, "gateway", "gw"), 40)
    except Exception:  # noqa: BLE001 — helper absent/raised → caller falls back
        return None
    return out


def profinet_asset_inventory(target: Any) -> dict:
    """[READ] Build a PROFINET asset register from a DCP IdentifyAll sweep.

    Vendor-neutral asset rows (station / MAC / IP / vendor-id / device-id / roles)
    for every station on the segment — segment-wide passive-style discovery, not
    an active per-device fingerprint.
    """
    discovered = profinet_discover(target)
    stations = discovered.get("stations", [])
    assets = [
        {
            "name_of_station": st["name_of_station"],
            "mac": st["mac"],
            "ip": st["ip"],
            "vendor_id": st["vendor_id"],
            "device_id": st["device_id"],
            "roles": st["device_roles"],
            "family": st["device_family"],
        }
        for st in stations
    ]
    controllers = [a for a in assets if "io_controller" in a["roles"]]
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "asset_count": len(assets),
        "io_controller_count": len(controllers),
        "io_device_count": sum(1 for a in assets if "io_device" in a["roles"]),
        "assets": assets,
        "method": "dcp_identify_all",
        "note": "PROFINET asset register via DCP IdentifyAll (layer-2 broadcast). "
        "Read-only; no per-device connection. Roles decoded from the DCP "
        "device-role bitmask.",
    }


def _station_before(dcp: Any, mac: str) -> dict | None:
    """Capture one station's current addressing (name + IP suite) by MAC, or None.

    Prefers the library's unicast DCP Get helpers; falls back to filtering an
    IdentifyAll sweep. Used to record the BEFORE state so a DCP Set is reversible.
    """
    wanted = str(mac or "").strip().lower()
    direct = _get_by_mac(dcp, mac)
    if direct is not None:
        return {k: direct.get(k) for k in ("name_of_station", "ip", "netmask", "gateway")}
    for d in list(dcp.identify_all() or [])[:MAX_STATIONS]:
        brief = _device_brief(d)
        if brief["mac"].strip().lower() == wanted:
            return {k: brief.get(k) for k in ("name_of_station", "ip", "netmask", "gateway")}
    return None


def profinet_dcp_set(
    target: Any,
    mac: str,
    set_name: str | None = None,
    set_ip: str | None = None,
    netmask: str | None = None,
    gateway: str | None = None,
    *,
    dry_run: bool = True,
) -> dict:
    """[WRITE][HIGH RISK] DCP Set: re-address one PROFINET station (name and/or IP).

    OT-dangerous — this changes a live device's name-of-station and/or IP suite via a
    unicast DCP Set, which can disrupt the IO connection. Captures the BEFORE
    addressing (by MAC) so the change is reversible, and refuses to act unless
    ``dry_run`` is explicitly False. 未经授权勿对生产控制系统写入.
    """
    wanted = str(mac or "").strip()
    if not wanted:
        return {"error": "mac is required (the station's MAC, e.g. '00:1b:1b:12:34:56')."}
    if not set_name and not set_ip:
        return {"error": "Nothing to set — provide set_name and/or set_ip."}
    endpoint = s(getattr(target, "name", ""), 64)
    would_set: dict = {}
    if set_name:
        would_set["name_of_station"] = s(set_name, 240)
    if set_ip:
        would_set["ip"] = s(set_ip, 40)
        would_set["netmask"] = s(netmask or "", 40)
        would_set["gateway"] = s(gateway or "", 40)
    with profinet_dcp(target) as dcp:
        before = _station_before(dcp, wanted)
        if dry_run:
            return {
                "endpoint": endpoint,
                "mac": s(mac, 24),
                "dry_run": True,
                "before": before,
                "would_set": would_set,
                "note": "Dry run — nothing set. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        if set_name:
            dcp.set_name_of_station(wanted, set_name)
        if set_ip:
            dcp.set_ip_address(wanted, [set_ip, netmask or "", gateway or ""])
    return {
        "endpoint": endpoint,
        "mac": s(mac, 24),
        "dry_run": False,
        "before": before,
        "set": would_set,
        "applied": True,
    }


__all__ = [
    "profinet_discover",
    "profinet_identify_station",
    "profinet_station_params",
    "profinet_asset_inventory",
    "profinet_dcp_set",
    "OTConnectionError",
]
