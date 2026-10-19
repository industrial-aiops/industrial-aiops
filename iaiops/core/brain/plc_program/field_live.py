"""Live values for MATCHED points only — read-only, opt-in, gaps stay gaps.

Asked for explicitly (``--live`` / ``live=True``); the cross-reference itself
touches no device. Each matched point is read through the endpoint's configured
ref, the same read the collector uses, and every answer carries when it arrived:

* ``status: read`` — a value, ``read_at`` (this host's clock when the answer came
  back) and ``freshness: read_now``. S7 and CIP return no device timestamp, so
  ``device_timestamp`` is ``None`` rather than our own clock dressed up as one.
* ``status: gap`` — the read failed or returned nothing. A gap has **no value
  key at all**: a failed read rendered as ``0`` or ``False`` is a stopped line
  reading as a quiet one.

Nothing is read when the program and endpoint share no address space — there is
nothing matched to read, and reading "something nearby" is the guess this
module refuses.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

MAX_LIVE_POINTS = 50

Reader = Callable[[Any, str], Any]


def default_read(target: Any, ref: str) -> Any:
    """One point through the protocol's own read; raises when it is not a value.

    EtherNet/IP goes through ``eip_read_tag`` so a per-tag CIP error (``good``
    False) is raised here, not returned as ``None`` for the caller to miss.
    """
    protocol = str(getattr(target, "protocol", "") or "").lower()
    if protocol in ("ethernetip", "eip"):
        from iaiops.connectors.eip import ops as eip_ops

        desc = eip_ops.eip_read_tag(target, ref)
        if not desc.get("good", False):
            raise ValueError(desc.get("error") or "tag read returned no good value")
        return desc.get("value")
    from iaiops.core.collect.reader import read_point

    value, _stamp = read_point(target, ref)
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _read_one(target: Any, row: dict[str, Any], read: Reader) -> dict[str, Any]:
    ref = row["configured_ref"]
    base = {"configured_ref": ref, "address": row["address"], "label": row.get("label", "")}
    try:
        value = read(target, ref)
    except Exception as exc:  # any failure is a gap — recorded, never swallowed
        return {**base, "status": "gap", "error": f"{type(exc).__name__}: {exc}"[:300]}
    read_at = _now()
    if value is None:
        return {**base, "status": "gap", "error": "the read returned no value", "read_at": read_at}
    return {
        **base,
        "status": "read",
        "value": value,
        "read_at": read_at,
        "freshness": "read_now",
        "device_timestamp": None,
    }


def read_matched(target: Any, xref: dict[str, Any], read: Reader | None = None) -> dict[str, Any]:
    """Read every matched point of an ``xref_program_endpoint`` result."""
    reader = read if read is not None else default_read
    matched = xref.get("matched")
    if xref.get("refused"):
        return {
            "points": [],
            "read_count": 0,
            "gap_count": 0,
            "note": f"refused ({xref['refused']}) — nothing is matched, so nothing is read",
        }
    if not xref.get("comparable") or matched is None:
        return {
            "points": [],
            "read_count": 0,
            "gap_count": 0,
            "note": "not comparable — nothing is matched, so nothing is read",
        }
    rows = list(matched)[:MAX_LIVE_POINTS]
    points = [_read_one(target, row, reader) for row in rows]
    gaps = sum(1 for p in points if p["status"] == "gap")
    return {
        "endpoint": str(getattr(target, "name", "")),
        "points": points,
        "read_count": len(points) - gaps,
        "gap_count": gaps,
        "not_read": max(0, len(matched) - len(rows)),
        "note": (
            "read_at is this host's clock when the answer arrived; the protocol carries "
            "no device timestamp. A gap is a failed or empty read and has no value."
        ),
    }


__all__ = ["MAX_LIVE_POINTS", "default_read", "read_matched"]
