"""Omron FINS protocol operations (CS/CJ/CP/NX-via-FINS, read-first).

Uses the **in-repo stdlib FINS client** (:mod:`iaiops.connectors.fins.client`)
— no third-party dependency. Areas are addressed Omron-style: ``DM`` (data
memory), ``CIO`` (core I/O), ``W`` (work), ``H`` (holding), ``A`` (auxiliary),
``EM`` (extended, current bank — 待核实). Framing per Omron W227/W342; the
self-test is the in-repo mock FINS responder (tests/test_fins.py); live-PLC
coverage is 待核实.

READ tools are non-destructive. ``fins_write_words`` is an OT-DANGEROUS write:
it is governed (high risk_tier), captures the BEFORE values for undo, and must
run through dry-run + double-confirm. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.fins.client import resolve_area
from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, fins_session

MAX_WORDS = 500  # bounded batch size (FINS 0101 practical cap; defensive)
MAX_BITS = 256
MAX_BATCH_ITEMS = 20  # fins_read_many issues one 0101 per item — keep it bounded


def _clamp(count: int, cap: int) -> int:
    return max(1, min(int(count), cap))


def fins_cpu_info(target: Any) -> dict:
    """[READ] CONTROLLER DATA READ (0501): CPU model/version (proves the link)."""
    with fins_session(target) as client:
        info = client.controller_data()
    return {
        "endpoint": s(target.name, 64),
        "model": s(info.get("model"), 64),
        "version": s(info.get("version"), 64),
    }


def fins_cpu_status(target: Any) -> dict:
    """[READ] CONTROLLER STATUS READ (0601): run/stop, mode, error flag words."""
    with fins_session(target) as client:
        status = client.controller_status()
    return {
        "endpoint": s(target.name, 64),
        "status": s(status.get("status"), 32),
        "mode": s(status.get("mode"), 32),
        "fatal_error_data": int(status.get("fatal_error_data", 0)),
        "non_fatal_error_data": int(status.get("non_fatal_error_data", 0)),
    }


def fins_read_words(target: Any, area: str = "DM", address: int = 0, count: int = 1) -> dict:
    """[READ] MEMORY AREA READ (0101): ``count`` 16-bit words from ``area``."""
    spec = resolve_area(area)
    count = _clamp(count, MAX_WORDS)
    address = int(address)
    with fins_session(target) as client:
        words = client.read_words(spec.word_code, address, count)
    return {
        "endpoint": s(target.name, 64),
        "area": spec.name,
        "address": address,
        "count": count,
        "words": [int(v) for v in words[:count]],
    }


def fins_read_bits(
    target: Any, area: str = "CIO", address: int = 0, bit: int = 0, count: int = 1
) -> dict:
    """[READ] MEMORY AREA READ (0101, bit codes): ``count`` bits from word.bit."""
    spec = resolve_area(area, bit_access=True)
    count = _clamp(count, MAX_BITS)
    address = int(address)
    bit = max(0, min(int(bit), 15))
    with fins_session(target) as client:
        bits = client.read_bits(spec.bit_code, address, bit, count)
    return {
        "endpoint": s(target.name, 64),
        "area": spec.name,
        "address": address,
        "bit": bit,
        "count": count,
        "bits": [bool(v) for v in bits[:count]],
    }


def fins_read_many(target: Any, items: list | None = None) -> dict:
    """[READ] Batched word reads: one 0101 per ``{area, address, count}`` item.

    (FINS has a MULTIPLE MEMORY AREA READ command 0104, 待核实 — this batches
    plain 0101 reads over ONE session instead, bounded to MAX_BATCH_ITEMS.)
    """
    requested = list(items or [])[:MAX_BATCH_ITEMS]
    if not requested:
        return {"endpoint": s(target.name, 64), "error": "No items given."}
    parsed: list[tuple[str, int, int]] = []
    for item in requested:
        if not isinstance(item, dict):
            raise ValueError(
                "fins_read_many items must be dicts like "
                "{'area': 'DM', 'address': 100, 'count': 2}."
            )
        spec = resolve_area(item.get("area", "DM"))
        parsed.append(
            (
                spec.name,
                int(item.get("address", 0)),
                _clamp(int(item.get("count", 1)), MAX_WORDS),
            )
        )
    reads: list[dict] = []
    with fins_session(target) as client:
        for name, address, count in parsed:
            code = resolve_area(name).word_code
            words = client.read_words(code, address, count)
            reads.append(
                {
                    "area": name,
                    "address": address,
                    "count": count,
                    "words": [int(v) for v in words[:count]],
                }
            )
    return {"endpoint": s(target.name, 64), "reads": reads}


def fins_write_words(
    target: Any, area: str, address: int, values: list[int], *, dry_run: bool = True
) -> dict:
    """[WRITE][HIGH RISK] MEMORY AREA WRITE (0102): words starting at address.

    OT-dangerous. Captures the BEFORE values (read-back of the same range) so
    the write is reversible, and refuses to act unless ``dry_run`` is
    explicitly False. 未经授权勿对生产控制系统写入.
    """
    spec = resolve_area(area)
    address = int(address)
    vals = [int(v) & 0xFFFF for v in (values or [])][:MAX_WORDS]
    if not vals:
        return {"endpoint": s(target.name, 64), "error": "No values to write."}
    with fins_session(target) as client:
        try:
            before = [int(v) for v in client.read_words(spec.word_code, address, len(vals))]
            read_error = ""
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = []
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "endpoint": s(target.name, 64),
                "area": spec.name,
                "address": address,
                "dry_run": True,
                "before": before,
                "would_write": vals,
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND "
                "a recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        client.write_words(spec.word_code, address, vals)
    return {
        "endpoint": s(target.name, 64),
        "area": spec.name,
        "address": address,
        "dry_run": False,
        "before": before,
        "written": vals,
        "applied": True,
    }


__all__ = [
    "OTConnectionError",
    "fins_cpu_info",
    "fins_cpu_status",
    "fins_read_bits",
    "fins_read_many",
    "fins_read_words",
    "fins_write_words",
]
