"""Change-of-value (CoV) monitor — bounded, read-only.

Polls a single point for a **bounded** window and returns only the value
*changes* (with timestamps), not every sample — the OT equivalent of a deadband
report. Works across protocols (OPC-UA / Modbus / S7 / Mitsubishi MC / EtherNet/IP)
by reusing each protocol's read path. Never an infinite loop: the window is
hard-capped by both a wall-clock duration and a maximum number of changes.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from iaiops.core.brain._shared import num, s

MAX_DURATION_S = 120
MAX_CHANGES = 500
MIN_INTERVAL_MS = 50


def _read_point(target: Any, ref: str) -> tuple[Any, str]:
    """Read one point across protocols → (value, source_timestamp). Best-effort.

    Dispatches through the capability registry; a protocol without a
    ``monitor_read`` capability raises the same teaching ``ValueError`` as before
    rather than silently returning a wrong value.
    """
    from iaiops.core.runtime.capabilities import UNSUPPORTED, get_capabilities

    protocol = getattr(target, "protocol", "")
    cap = get_capabilities(protocol)
    reader = cap.monitor_read if cap else UNSUPPORTED
    if reader is UNSUPPORTED:
        raise ValueError(f"No CoV read path for protocol '{protocol}'.")
    return reader(target, ref)


def _changed(prev: Any, curr: Any, deadband: float) -> bool:
    """True if ``curr`` differs from ``prev`` beyond the (numeric) deadband."""
    if prev is None:
        return True
    pn, cn = num(prev), num(curr)
    if pn is not None and cn is not None:
        return abs(cn - pn) > max(0.0, deadband)
    return curr != prev


def monitor_changes(
    target: Any,
    ref: str,
    duration_s: int = 10,
    interval_ms: int = 500,
    deadband: float = 0.0,
    max_changes: int = 100,
) -> dict:
    """[READ] Capture only the value CHANGES of a point over a bounded window.

    Polls ``ref`` every ``interval_ms`` for at most ``duration_s`` seconds (both
    hard-capped) and records a change whenever the value moves beyond ``deadband``
    (numeric) or differs (non-numeric). Returns the change list — never the full
    sample stream, and never an unbounded loop.
    """
    duration_s = max(1, min(int(duration_s), MAX_DURATION_S))
    interval_ms = max(MIN_INTERVAL_MS, int(interval_ms))
    max_changes = max(1, min(int(max_changes), MAX_CHANGES))
    deadline = time.monotonic() + duration_s

    changes: list[dict] = []
    samples = 0
    prev: Any = None
    have_prev = False
    while time.monotonic() < deadline and len(changes) < max_changes:
        samples += 1
        try:
            value, src_ts = _read_point(target, ref)
        except Exception as exc:  # noqa: BLE001 — record per-sample read error
            changes.append(
                {"error": s(str(exc), 200), "wall_clock": datetime.now(tz=UTC).isoformat()}
            )
            break
        if not have_prev or _changed(prev, value, deadband):
            changes.append(
                {
                    "value": value,
                    "previous": prev if have_prev else None,
                    "source_timestamp": s(src_ts, 64),
                    "wall_clock": datetime.now(tz=UTC).isoformat(timespec="milliseconds"),
                }
            )
            prev = value
            have_prev = True
        time.sleep(interval_ms / 1000.0)
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "ref": s(ref, 96),
        "duration_s": duration_s,
        "interval_ms": interval_ms,
        "deadband": deadband,
        "samples_polled": samples,
        "change_count": len(changes),
        "changes": changes,
        "note": "Bounded change-of-value capture (only changes returned, not every "
        "sample). Hard-capped by duration_s and max_changes — never an open loop.",
    }


__all__ = ["monitor_changes"]
