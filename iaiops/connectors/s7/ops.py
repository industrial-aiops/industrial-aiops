"""S7comm operations for Siemens + 仿西门子 国产 PLCs (read-first).

Uses ``pyS7`` — a **pure-Python** ISO-on-TCP (RFC1006) S7 client — so the venv
installs with no native ``libsnap7`` dependency. Covers S7-300/400/1200/1500 and
compatible domestic clones over the standard S7 "PUT/GET" protocol; memory areas
DB (data blocks), M (merker/flags), I (inputs), Q (outputs). No authentication is
part of S7comm — access is gated at the CPU ("Permit access with PUT/GET").

Addresses follow the pyS7 syntax (e.g. ``DB1,REAL4``, ``DB1,X0.0``, ``MW10``,
``I0.0``); ``s7_read_area`` / ``s7_read_db`` build them from area + type + offset.

READ tools are non-destructive. ``s7_write_db`` is an OT-DANGEROUS write — it is
governed (high risk_tier), captures the BEFORE value for undo, and must run
through dry-run + double-confirm. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, s7_session

MAX_READ_ITEMS = 100

# S7 data types pyS7 understands, with their byte stride (0 = bit-addressed).
_DTYPE_SIZE = {
    "BIT": 0, "BYTE": 1, "CHAR": 1, "USINT": 1, "SINT": 1,
    "WORD": 2, "INT": 2, "DWORD": 4, "DINT": 4, "REAL": 4, "LREAL": 8,
}
_AREA_LETTER = {"M": "M", "I": "I", "E": "I", "Q": "Q", "A": "Q"}
_NONDB_SUFFIX = {"BYTE": "B", "WORD": "W", "INT": "W", "DWORD": "D",
                 "DINT": "D", "REAL": "D", "LREAL": "D"}


def _s7_addr(area: str, dtype: str, start: int, db: int, bit: int = 0) -> str:
    """Build a pyS7 address string from area/type/offset (vendor-neutral S7)."""
    area = area.upper()
    dtype = dtype.upper()
    if area == "DB":
        if dtype == "BIT":
            return f"DB{db},X{start}.{bit}"
        return f"DB{db},{dtype}{start}"
    letter = _AREA_LETTER.get(area, "M")
    if dtype == "BIT":
        return f"{letter}{start}.{bit}"
    return f"{letter}{_NONDB_SUFFIX.get(dtype, 'W')}{start}"


def _addr_series(area: str, dtype: str, start: int, db: int, bit: int, count: int) -> list[str]:
    """Generate ``count`` consecutive addresses of the same type."""
    count = max(1, min(int(count), MAX_READ_ITEMS))
    dtype = dtype.upper()
    out: list[str] = []
    if dtype == "BIT":
        byte, b = start, bit
        for _ in range(count):
            out.append(_s7_addr(area, "BIT", byte, db, b))
            b += 1
            if b > 7:
                b, byte = 0, byte + 1
        return out
    stride = _DTYPE_SIZE.get(dtype, 2) or 2
    return [_s7_addr(area, dtype, start + i * stride, db, bit) for i in range(count)]


def _coerce(value: Any) -> Any:
    """Make an S7 value JSON-safe (scalars pass through; tuples → lists)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value][:MAX_READ_ITEMS]
    return s(value, 256)


def s7_cpu_info(target: Any) -> dict:
    """[READ] S7 CPU identity (module/serial/version) and run/stop status."""
    with s7_session(target) as client:
        info: dict = {}
        try:
            info = dict(client.get_cpu_info())
        except Exception as exc:  # noqa: BLE001 — some CPUs deny SZL reads
            info = {"info_error": s(str(exc), 160)}
        try:
            status = client.get_cpu_status()
        except Exception as exc:  # noqa: BLE001
            status = s(str(exc), 80)
    return {
        "endpoint": s(target.name, 64),
        "rack": target.rack,
        "slot": target.slot,
        "cpu_status": s(status, 64),
        "cpu_info": {s(k, 48): _coerce(v) for k, v in info.items()},
    }


def s7_read_area(
    target: Any, area: str, dtype: str, start: int, db: int = 0, count: int = 1, bit: int = 0
) -> dict:
    """[READ] Read ``count`` items of ``dtype`` from S7 area DB/M/I/Q at ``start``."""
    addresses = _addr_series(area, dtype, start, db, bit, count)
    with s7_session(target) as client:
        values = client.read(addresses)
    return {
        "endpoint": s(target.name, 64),
        "area": s(area.upper(), 8),
        "db": db,
        "dtype": s(dtype.upper(), 12),
        "start": start,
        "count": len(addresses),
        "items": [
            {"address": s(a, 48), "value": _coerce(v)}
            for a, v in zip(addresses, values, strict=False)
        ],
    }


def s7_read_db(target: Any, db: int, dtype: str, start: int, count: int = 1) -> dict:
    """[READ] Read ``count`` ``dtype`` items from data block ``db`` at byte ``start``."""
    return s7_read_area(target, "DB", dtype, start, db=db, count=count)


def s7_read_many(target: Any, addresses: list[str]) -> dict:
    """[READ] Batch-read raw pyS7 address strings (e.g. ['DB1,REAL4','I0.0'])."""
    addrs = [str(a) for a in (addresses or [])][:MAX_READ_ITEMS]
    if not addrs:
        return {"endpoint": s(target.name, 64), "items": [], "error": "No addresses given."}
    with s7_session(target) as client:
        values = client.read(addrs)
    return {
        "endpoint": s(target.name, 64),
        "count": len(addrs),
        "items": [
            {"address": s(a, 48), "value": _coerce(v)}
            for a, v in zip(addrs, values, strict=False)
        ],
    }


def s7_write_db(
    target: Any, db: int, dtype: str, start: int, value: Any, *, dry_run: bool = True
) -> dict:
    """[WRITE][HIGH RISK] Write one ``dtype`` value to data block ``db`` at ``start``.

    OT-dangerous. Captures the BEFORE value (read-back) so the write is
    reversible, and refuses to act unless ``dry_run`` is explicitly False.
    未经授权勿对生产控制系统写入.
    """
    address = _s7_addr("DB", dtype, start, db)
    with s7_session(target) as client:
        try:
            before = _coerce(client.read([address])[0])
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = None
            read_error = s(str(exc), 160)
        else:
            read_error = ""
        if dry_run:
            return {
                "endpoint": s(target.name, 64),
                "address": s(address, 48),
                "dry_run": True,
                "before": before,
                "would_write": _coerce(value),
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        client.write([address], [_typed_value(dtype, value)])
    return {
        "endpoint": s(target.name, 64),
        "address": s(address, 48),
        "dry_run": False,
        "before": before,
        "written": _coerce(value),
        "applied": True,
    }


def _typed_value(dtype: str, value: Any) -> Any:
    """Coerce ``value`` to the Python type S7 expects for ``dtype``."""
    dtype = dtype.upper()
    if dtype == "BIT":
        return bool(value)
    if dtype in ("REAL", "LREAL"):
        return float(value)
    if dtype in _DTYPE_SIZE:
        return int(value)
    return value


__all__ = [
    "s7_cpu_info",
    "s7_read_area",
    "s7_read_db",
    "s7_read_many",
    "s7_write_db",
    "OTConnectionError",
]
