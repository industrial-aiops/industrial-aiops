"""Active asset inventory / fingerprint (IEC 62443-flavored), read-only.

For each configured (or supplied) target this **actively connects** with our own
protocol client and reads the device's *identity* call — vendor / model /
firmware / serial — then aggregates everything into an asset-register JSON.

Honesty note (important): this is **ACTIVE fingerprinting via our client
connections**, NOT passive SPAN/tap discovery. It will only find devices we are
configured to reach and that answer an identity query; it adds (light) load to
each device. Passive, traffic-mirroring discovery (no connections) is a roadmap
item. Each probe is defensive — an unreachable device becomes an
``reachable: false`` row, never a raised exception.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from iaiops.core.brain._shared import s

MAX_TARGETS = 500


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _endpoint_addr(target: Any) -> str:
    """Human-readable address for a target, per protocol."""
    proto = getattr(target, "protocol", "")
    if proto == "opcua":
        return getattr(target, "endpoint_url", "") or "?"
    if proto == "mtconnect":
        return getattr(target, "agent_url", "") or f"{target.host}:{target.port}"
    host = getattr(target, "host", "")
    port = getattr(target, "port", 0)
    return f"{host}:{port}" if host else "?"


def _fingerprint_one(target: Any) -> dict:
    """Actively fingerprint one target; never raises (errors → reachable:false)."""
    proto = getattr(target, "protocol", "")
    base = {
        "endpoint": s(getattr(target, "name", ""), 64),
        "protocol": s(proto, 16),
        "address": s(_endpoint_addr(target), 200),
        "vendor": "",
        "model": "",
        "firmware": "",
        "serial": "",
        "reachable": False,
        "last_seen": "",
        "error": "",
    }
    try:
        fields = _probe_identity(target, proto)
        base.update(fields)
        base["reachable"] = True
        base["last_seen"] = _now_iso()
    except Exception as exc:  # noqa: BLE001 — unreachable is a status, not a crash
        base["error"] = s(str(exc), 200)
    return base


def _probe_identity(target: Any, proto: str) -> dict:
    """Per-protocol identity call → {vendor, model, firmware, serial}."""
    if proto == "opcua":
        from iaiops.connectors.opcua.ops import server_info

        info = server_info(target)
        return {
            "vendor": s(info.get("manufacturer", ""), 96),
            "model": s(info.get("product_name", ""), 96),
            "firmware": s(info.get("software_version", ""), 64),
        }
    if proto == "s7":
        from iaiops.connectors.s7.ops import s7_cpu_info

        info = s7_cpu_info(target)
        cpu = info.get("cpu_info", {})
        return {
            "vendor": "Siemens/compatible",
            "model": s(cpu.get("ModuleName", cpu.get("ModuleTypeName", "")), 96),
            "firmware": s(cpu.get("Version", ""), 64),
            "serial": s(cpu.get("SerialNumber", ""), 64),
        }
    if proto in ("ethernetip", "eip"):
        from iaiops.connectors.eip.ops import eip_controller_info

        info = eip_controller_info(target)
        ctrl = info.get("controller", {})
        return {
            "vendor": s(str(ctrl.get("vendor", "Rockwell/Allen-Bradley")), 96),
            "model": s(str(ctrl.get("product_name", ctrl.get("product_type", ""))), 96),
            "firmware": s(str(ctrl.get("revision", ctrl.get("version", ""))), 64),
            "serial": s(str(ctrl.get("serial", "")), 64),
        }
    if proto == "mc":
        from iaiops.connectors.mc.ops import mc_cpu_status

        info = mc_cpu_status(target)
        return {
            "vendor": "Mitsubishi/compatible",
            "model": s(info.get("cpu_type", ""), 96),
            "firmware": s(info.get("cpu_code", ""), 64),
        }
    if proto == "modbus":
        return _modbus_identity(target)
    if proto == "mtconnect":
        from iaiops.connectors.mtconnect.ops import mtconnect_probe

        info = mtconnect_probe(target)
        devices = info.get("devices", [])
        first = devices[0] if devices else {}
        return {
            "vendor": "MTConnect agent",
            "model": s(first.get("name", ""), 96),
            "serial": s(first.get("uuid", ""), 96),
        }
    raise ValueError(f"No identity probe for protocol '{proto}'.")


def _modbus_identity(target: Any) -> dict:
    """Modbus Device Identification (FC43 / 0x2B MEI 14), where supported."""
    from iaiops.core.runtime.connection import modbus_session

    with modbus_session(target) as client:
        read_dev = getattr(client, "read_device_information", None)
        if read_dev is None:
            return {"vendor": "", "model": "", "firmware": ""}
        resp = read_dev(device_id=getattr(target, "unit_id", 1))
        if resp is None or (hasattr(resp, "isError") and resp.isError()):
            return {"vendor": "", "model": "", "firmware": ""}
        info = {k: v for k, v in getattr(resp, "information", {}).items()}
    # Standard MEI object ids: 0 vendor, 1 product code, 2 revision.
    return {
        "vendor": s(_mei(info, 0), 96),
        "model": s(_mei(info, 1), 96),
        "firmware": s(_mei(info, 2), 64),
    }


def _mei(info: dict, key: int) -> str:
    """Decode a Modbus MEI object value (bytes or str) to text."""
    val = info.get(key, info.get(str(key), ""))
    if isinstance(val, (bytes, bytearray)):
        return val.decode("latin-1", "replace")
    return str(val or "")


def asset_inventory(targets: list[Any]) -> dict:
    """[READ] Actively fingerprint a list of targets into an asset register.

    Each target is connected to with our own client and its identity call read;
    the result is one register row per device. ACTIVE fingerprinting (not passive
    discovery) — see the module docstring.
    """
    items = list(targets or [])[:MAX_TARGETS]
    assets = [_fingerprint_one(t) for t in items]
    reachable = sum(1 for a in assets if a["reachable"])
    return {
        "asset_count": len(assets),
        "reachable_count": reachable,
        "unreachable_count": len(assets) - reachable,
        "assets": assets,
        "method": "active_fingerprint",
        "note": "ACTIVE fingerprinting via our protocol clients (connects to each "
        "configured device and reads its identity). NOT passive SPAN/tap "
        "discovery — passive traffic-based discovery is a roadmap item.",
    }


__all__ = ["asset_inventory"]
