"""EtherCAT operations — REAL fieldbus master via ``pysoem`` / SOEM (read-first).

EtherCAT is a hard-real-time fieldbus, NOT a TCP request/response protocol: a
*master* owns the bus cycle. This driver uses ``pysoem`` (the Python binding for
the SOEM C library), which is an **OPTIONAL dependency** (``pip install
iaiops[ethercat]``) imported LAZILY in
:func:`iaiops.core.runtime.connection._build_ethercat_master`.

HARD REQUIREMENTS (no way around them): **Linux**, **root or CAP_NET_RAW**, a
**dedicated NIC** cabled to the bus, and **real EtherCAT slave hardware**. There
is **NO software simulator** (unlike OPC-UA / Modbus), it is **not testable in
mock-only CI**, and **macOS is effectively unsupported**. Every tool therefore
degrades gracefully (a teaching ``OTConnectionError`` → sanitized error dict) when
pysoem is missing, raw-socket permission is denied, the NIC is wrong, or no slave
answers — it never crashes and never requires pysoem at import time.

READ tools are non-destructive. ``ethercat_write_sdo`` (CoE SDO download) and
``ethercat_set_state`` (AL-state transition) are OT-DANGEROUS writes: governed
(high risk_tier), capture the BEFORE value/state for undo, and refuse to act
unless ``dry_run`` is explicitly False. Changing EtherCAT state can START or STOP
machine motion. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, ethercat_master

MAX_SLAVES = 256  # bounded enumeration (defensive against a runaway bus scan)
MAX_OD_OBJECTS = 200  # bounded object-dictionary summary
MAX_PDO_BYTES = 1024  # bounded process-data snapshot

# EtherCAT AL-state numeric codes ↔ names (SOEM/ETG.1000 values).
EC_STATE_NAMES: dict[int, str] = {
    0: "NONE", 1: "INIT", 2: "PREOP", 3: "BOOT", 4: "SAFEOP", 8: "OP",
}
EC_STATE_VALUES: dict[str, int] = {v: k for k, v in EC_STATE_NAMES.items()}


def _state_name(value: Any) -> str:
    """Map a numeric AL-state to its name (best-effort; unknown → the number)."""
    try:
        code = int(value)
    except (TypeError, ValueError):
        return s(value, 16)
    # The low nibble is the actual state; the 0x10 bit is the AL-error flag.
    name = EC_STATE_NAMES.get(code & 0x0F)
    if name is None:
        return f"0x{code:02X}"
    return f"{name}+ERR" if code & 0x10 else name


def _resolve_state(state: str | int) -> int:
    """Resolve a requested target state (name or number) to its numeric code."""
    if isinstance(state, int):
        return state
    key = str(state).strip().upper()
    if key in EC_STATE_VALUES:
        return EC_STATE_VALUES[key]
    raise ValueError(
        f"Unknown EtherCAT state '{state}'. Use one of: "
        f"{', '.join(EC_STATE_VALUES)} (or a numeric AL-state code)."
    )


def _hexlify(data: Any) -> str:
    """Render raw SDO/PDO bytes as a bounded hex string (never raises)."""
    try:
        return bytes(data)[:MAX_PDO_BYTES].hex()
    except (TypeError, ValueError):
        return ""


def _as_int(data: Any) -> int | None:
    """Interpret raw little-endian SDO bytes as an unsigned int (≤8 bytes)."""
    try:
        raw = bytes(data)
    except (TypeError, ValueError):
        return None
    if not raw or len(raw) > 8:
        return None
    return int.from_bytes(raw, "little", signed=False)


def _slave_at(master: Any, index: int) -> Any:
    """Return ``master.slaves[index]`` with a teaching bounds error."""
    slaves = list(getattr(master, "slaves", []) or [])
    if not slaves:
        raise OTConnectionError(
            "No EtherCAT slaves found on the bus. Check the NIC, cabling, slave "
            "power, and that real slaves are present (no simulator exists).",
            protocol="ethercat",
        )
    if index < 0 or index >= len(slaves):
        raise OTConnectionError(
            f"Slave index {index} out of range — {len(slaves)} slave(s) on the bus "
            f"(0..{len(slaves) - 1}). Call ethercat_slaves to enumerate.",
            protocol="ethercat",
        )
    return slaves[index]


def _slave_brief(index: int, sl: Any) -> dict:
    """Normalize one pysoem slave to a JSON-safe identity descriptor."""
    return {
        "index": index,
        "name": s(getattr(sl, "name", ""), 96),
        "vendor_id": int(getattr(sl, "man", 0) or 0),
        "product_code": int(getattr(sl, "id", 0) or 0),
        "revision": int(getattr(sl, "rev", 0) or 0),
        "config_addr": int(getattr(sl, "config_addr", 0) or 0),
        "state": _state_name(getattr(sl, "state", 0)),
    }


def ethercat_master_state(target: Any) -> dict:
    """[READ] Open the master and report master/working-counter + slave counts."""
    with ethercat_master(target) as master:
        slaves = list(getattr(master, "slaves", []) or [])
        found = len(slaves)
        try:
            lowest = master.read_state()
        except Exception as exc:  # noqa: BLE001 — report, do not crash
            lowest = getattr(master, "state", 0)
            state_error = s(str(exc), 160)
        else:
            state_error = ""
        expected_wkc = int(getattr(master, "expected_wkc", 0) or 0)
    expected = int(getattr(target, "expected_slaves", 0) or 0)
    return {
        "endpoint": s(target.name, 64),
        "nic": s(getattr(target, "nic", "") or getattr(target, "host", ""), 48),
        "master_state": _state_name(lowest),
        "expected_working_counter": expected_wkc,
        "slaves_found": found,
        "slaves_expected": expected,
        "slave_count_ok": (expected == 0) or (expected == found),
        "state_error": state_error,
    }


def ethercat_slaves(target: Any) -> dict:
    """[READ] Bus scan: enumerate every slave (id/vendor/product/rev/addr/state)."""
    with ethercat_master(target) as master:
        try:
            master.read_state()
        except Exception:  # noqa: BLE001 — state refresh is best-effort
            pass
        slaves = list(getattr(master, "slaves", []) or [])[:MAX_SLAVES]
        items = [_slave_brief(i, sl) for i, sl in enumerate(slaves)]
    return {
        "endpoint": s(target.name, 64),
        "slave_count": len(items),
        "slaves": items,
    }


def _sm_config(sl: Any) -> list[dict]:
    """Best-effort Sync-Manager config summary (bounded; never raises)."""
    out: list[dict] = []
    try:
        for i in range(8):
            sm = sl.sm[i]
            start = int(getattr(sm, "start_addr", 0) or 0)
            length = int(getattr(sm, "sm_length", 0) or 0)
            if start == 0 and length == 0:
                continue
            out.append({
                "index": i,
                "start_addr": start,
                "length": length,
                "flags": int(getattr(sm, "sm_flags", 0) or 0),
            })
    except Exception:  # noqa: BLE001 — SM table is optional/driver-specific
        return out
    return out


def _fmmu_config(sl: Any) -> list[dict]:
    """Best-effort FMMU config summary (bounded; never raises)."""
    out: list[dict] = []
    try:
        for i in range(8):
            fm = sl.fmmu[i]
            la = int(getattr(fm, "log_start", 0) or 0)
            length = int(getattr(fm, "log_length", 0) or 0)
            if la == 0 and length == 0:
                continue
            out.append({
                "index": i,
                "log_start": la,
                "log_length": length,
                "type": int(getattr(fm, "fmmu_type", 0) or 0),
            })
    except Exception:  # noqa: BLE001 — FMMU table is optional/driver-specific
        return out
    return out


def _od_summary(sl: Any) -> list[dict]:
    """Best-effort CoE object-dictionary summary via SDO-info (bounded)."""
    out: list[dict] = []
    try:
        objects = list(getattr(sl, "od", []) or [])[:MAX_OD_OBJECTS]
    except Exception:  # noqa: BLE001 — many slaves do not serve SDO-info
        return out
    for obj in objects:
        try:
            entries = list(getattr(obj, "entries", []) or [])
        except Exception:  # noqa: BLE001
            entries = []
        out.append({
            "index": f"0x{int(getattr(obj, 'index', 0) or 0):04X}",
            "name": s(getattr(obj, "name", ""), 64),
            "entry_count": len(entries),
        })
    return out


def ethercat_slave_info(target: Any, slave: int) -> dict:
    """[READ] Detail one slave: identity, SM/FMMU config, OD summary, PDO sizes."""
    with ethercat_master(target) as master:
        try:
            master.read_state()
        except Exception:  # noqa: BLE001 — best-effort
            pass
        sl = _slave_at(master, int(slave))
        brief = _slave_brief(int(slave), sl)
        input_bytes = len(bytes(getattr(sl, "input", b"") or b""))
        output_bytes = len(bytes(getattr(sl, "output", b"") or b""))
        sm = _sm_config(sl)
        fmmu = _fmmu_config(sl)
        od = _od_summary(sl)
    return {
        "endpoint": s(target.name, 64),
        **brief,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "sync_managers": sm,
        "fmmus": fmmu,
        "object_dictionary": od,
        "od_note": "Object dictionary via CoE SDO-info; empty when the slave does "
        "not serve it. SM/FMMU summarize the mailbox/process-data mapping.",
    }


def ethercat_read_sdo(
    target: Any, slave: int, index: int, subindex: int = 0, size: int = 0
) -> dict:
    """[READ] CoE SDO upload: read one object-dictionary entry (acyclic mailbox)."""
    with ethercat_master(target) as master:
        sl = _slave_at(master, int(slave))
        raw = sl.sdo_read(int(index), int(subindex), int(size) or None)
    data = bytes(raw or b"")[:MAX_PDO_BYTES]
    return {
        "endpoint": s(target.name, 64),
        "slave": int(slave),
        "index": f"0x{int(index):04X}",
        "subindex": int(subindex),
        "byte_length": len(data),
        "hex": data.hex(),
        "as_uint": _as_int(data),
    }


def ethercat_read_pdo(target: Any, slave: int) -> dict:
    """[READ] One cyclic snapshot of a slave's input process-data image (bounded)."""
    with ethercat_master(target, map_pdo=True) as master:
        sl = _slave_at(master, int(slave))
        master.send_processdata()
        try:
            wkc = int(master.receive_processdata(2000))
        except Exception as exc:  # noqa: BLE001 — report, do not crash
            wkc = -1
            recv_error = s(str(exc), 160)
        else:
            recv_error = ""
        in_data = bytes(getattr(sl, "input", b"") or b"")[:MAX_PDO_BYTES]
        out_len = len(bytes(getattr(sl, "output", b"") or b""))
    return {
        "endpoint": s(target.name, 64),
        "slave": int(slave),
        "working_counter": wkc,
        "input_byte_length": len(in_data),
        "input_hex": in_data.hex(),
        "output_byte_length": out_len,
        "recv_error": recv_error,
        "note": "Single cyclic read (never loops). WKC < expected means a slave "
        "did not respond. Read-only snapshot of the input image.",
    }


def ethercat_write_sdo(
    target: Any,
    slave: int,
    index: int,
    value: Any,
    subindex: int = 0,
    *,
    dry_run: bool = True,
) -> dict:
    """[WRITE][HIGH RISK] CoE SDO download: write one object-dictionary entry.

    OT-dangerous. ``value`` is a hex string (e.g. ``"01"`` / ``"e803"``, raw
    little-endian bytes as written on the wire). Captures the BEFORE value
    (SDO read-back) so the write is reversible, and refuses to act unless
    ``dry_run`` is explicitly False. 未经授权勿对生产控制系统写入.
    """
    try:
        payload = bytes.fromhex(str(value).replace(" ", ""))
    except ValueError as exc:
        raise ValueError(
            f"EtherCAT SDO value must be a hex string of the raw little-endian "
            f"bytes (e.g. 'e803' for 1000 as uint16). Got: {value!r}."
        ) from exc
    with ethercat_master(target) as master:
        sl = _slave_at(master, int(slave))
        try:
            before_raw = bytes(sl.sdo_read(int(index), int(subindex)) or b"")
            before = before_raw[:MAX_PDO_BYTES].hex()
            read_error = ""
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = ""
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "endpoint": s(target.name, 64),
                "slave": int(slave),
                "index": f"0x{int(index):04X}",
                "subindex": int(subindex),
                "dry_run": True,
                "before": before,
                "would_write": payload.hex(),
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        sl.sdo_write(int(index), int(subindex), payload)
    return {
        "endpoint": s(target.name, 64),
        "slave": int(slave),
        "index": f"0x{int(index):04X}",
        "subindex": int(subindex),
        "dry_run": False,
        "before": before,
        "written": payload.hex(),
        "applied": True,
    }


def ethercat_set_state(
    target: Any,
    state: str,
    slave: int = -1,
    *,
    dry_run: bool = True,
) -> dict:
    """[WRITE][HIGH RISK] Request an AL-state transition (slave or master-wide).

    OT-dangerous: moving to/from OP can START or STOP machine motion. ``slave``
    < 0 applies to the master (all slaves). Captures the CURRENT state for undo
    and refuses to act unless ``dry_run`` is explicitly False.
    未经授权勿对生产控制系统写入.
    """
    target_code = _resolve_state(state)
    target_name = _state_name(target_code)
    is_master = int(slave) < 0
    with ethercat_master(target, map_pdo=True) as master:
        if is_master:
            try:
                master.read_state()
            except Exception:  # noqa: BLE001 — best-effort capture
                pass
            before = _state_name(getattr(master, "state", 0))
        else:
            sl = _slave_at(master, int(slave))
            before = _state_name(getattr(sl, "state", 0))
        if dry_run:
            return {
                "endpoint": s(target.name, 64),
                "scope": "master" if is_master else f"slave[{int(slave)}]",
                "dry_run": True,
                "before": before,
                "would_request": target_name,
                "note": "Dry run — no state change. Re-run with dry_run=False AND a "
                "recorded approver to apply. Changing EtherCAT state can start/stop "
                "machine motion. 未经授权勿对生产控制系统写入.",
            }
        obj = master if is_master else _slave_at(master, int(slave))
        obj.state = target_code
        obj.write_state()
        try:
            reached = _state_name(obj.state_check(target_code, 50000))
        except Exception as exc:  # noqa: BLE001 — report, do not crash
            reached = before
            check_error = s(str(exc), 160)
        else:
            check_error = ""
    return {
        "endpoint": s(target.name, 64),
        "scope": "master" if is_master else f"slave[{int(slave)}]",
        "dry_run": False,
        "before": before,
        "requested": target_name,
        "reached": reached,
        "applied": True,
        "check_error": check_error,
    }


__all__ = [
    "ethercat_master_state",
    "ethercat_slaves",
    "ethercat_slave_info",
    "ethercat_read_sdo",
    "ethercat_read_pdo",
    "ethercat_write_sdo",
    "ethercat_set_state",
    "OTConnectionError",
]
