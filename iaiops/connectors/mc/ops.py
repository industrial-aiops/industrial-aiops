"""Mitsubishi MC protocol operations (三菱 Q/L/iQ-R/iQ-L, read-first).

Uses ``pymcprotocol`` — a **pure-Python** MELSEC Communication (MC) 3E-frame
client (binary), so the venv installs with no native dependency. Devices are
addressed MELSEC-style: ``D`` (data register), ``M`` (internal relay), ``X``/``Y``
(I/O), ``W`` (link register), etc. Only the 3E frame is implemented by the
library (1E/4E are not supported here).

READ tools are non-destructive. ``mc_write_words`` is an OT-DANGEROUS write: it
is governed (high risk_tier), captures the BEFORE values for undo, and must run
through dry-run + double-confirm. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, mc_session

MAX_POINTS = 256  # bounded batch size (defensive against agent over-requests)


def _clamp(count: int) -> int:
    return max(1, min(int(count), MAX_POINTS))


def mc_cpu_status(target: Any) -> dict:
    """[READ] MELSEC CPU type/code identity (proves the MC link is alive)."""
    with mc_session(target) as client:
        cputype, cpucode = client.read_cputype()
    return {
        "endpoint": s(target.name, 64),
        "plctype": s(target.plctype, 16),
        "cpu_type": s(cputype, 64),
        "cpu_code": s(cpucode, 16),
    }


def mc_read_words(target: Any, headdevice: str, count: int = 1) -> dict:
    """[READ] Batch-read ``count`` 16-bit word devices from ``headdevice`` (e.g. D100)."""
    count = _clamp(count)
    with mc_session(target) as client:
        values = client.batchread_wordunits(headdevice=headdevice, readsize=count)
    return {
        "endpoint": s(target.name, 64),
        "headdevice": s(headdevice, 32),
        "count": count,
        "words": [int(v) for v in list(values)[:count]],
    }


def mc_read_bits(target: Any, headdevice: str, count: int = 1) -> dict:
    """[READ] Batch-read ``count`` bit devices from ``headdevice`` (e.g. M0, X10)."""
    count = _clamp(count)
    with mc_session(target) as client:
        values = client.batchread_bitunits(headdevice=headdevice, readsize=count)
    return {
        "endpoint": s(target.name, 64),
        "headdevice": s(headdevice, 32),
        "count": count,
        "bits": [bool(v) for v in list(values)[:count]],
    }


def mc_read_many(
    target: Any, word_devices: list[str] | None = None, dword_devices: list[str] | None = None
) -> dict:
    """[READ] Random-read scattered word + dword devices in one MC request."""
    words = [str(d) for d in (word_devices or [])][:MAX_POINTS]
    dwords = [str(d) for d in (dword_devices or [])][:MAX_POINTS]
    if not words and not dwords:
        return {"endpoint": s(target.name, 64), "error": "No devices given."}
    with mc_session(target) as client:
        wvals, dvals = client.randomread(word_devices=words, dword_devices=dwords)
    return {
        "endpoint": s(target.name, 64),
        "words": [
            {"device": s(d, 32), "value": int(v)}
            for d, v in zip(words, list(wvals), strict=False)
        ],
        "dwords": [
            {"device": s(d, 32), "value": int(v)}
            for d, v in zip(dwords, list(dvals), strict=False)
        ],
    }


def mc_write_words(
    target: Any, headdevice: str, values: list[int], *, dry_run: bool = True
) -> dict:
    """[WRITE][HIGH RISK] Write 16-bit words starting at ``headdevice``.

    OT-dangerous. Captures the BEFORE values (read-back of the same range) so the
    write is reversible, and refuses to act unless ``dry_run`` is explicitly
    False. 未经授权勿对生产控制系统写入.
    """
    vals = [int(v) for v in (values or [])][:MAX_POINTS]
    if not vals:
        return {"endpoint": s(target.name, 64), "error": "No values to write."}
    with mc_session(target) as client:
        try:
            before = [int(v) for v in client.batchread_wordunits(
                headdevice=headdevice, readsize=len(vals))]
            read_error = ""
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = []
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "endpoint": s(target.name, 64),
                "headdevice": s(headdevice, 32),
                "dry_run": True,
                "before": before,
                "would_write": vals,
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        client.batchwrite_wordunits(headdevice=headdevice, values=vals)
    return {
        "endpoint": s(target.name, 64),
        "headdevice": s(headdevice, 32),
        "dry_run": False,
        "before": before,
        "written": vals,
        "applied": True,
    }


__all__ = [
    "mc_cpu_status",
    "mc_read_words",
    "mc_read_bits",
    "mc_read_many",
    "mc_write_words",
    "OTConnectionError",
]
