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

Nothing is read when the program and endpoint share no address space. For
Logix the L5X controller name must also match the live name (only a name check,
not a unique hardware identity). AWL/SCL has no CPU identity, so only a CLI
operator attestation permits live values, and the CPU must report RUN.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

MAX_LIVE_POINTS = 50

Reader = Callable[[Any, str], Any]


def _identity(target: Any, xref: dict[str, Any], export_confirmed: bool) -> dict[str, Any]:
    """Check the live controller before attaching readings to an export.

    AWL/SCL contains no CPU identifier. Only an operator can attest its origin;
    this is reported as an attestation, never dressed up as device verification.
    """
    protocol = str(getattr(target, "protocol", "") or "").lower()
    if protocol in ("ethernetip", "eip"):
        from iaiops.connectors.eip.ops import eip_controller_info

        exported = str(xref.get("program", {}).get("controller", {}).get("name") or "").strip()
        if not exported:
            return {"status": "unverified", "reason": "L5X has no controller name"}
        try:
            info = eip_controller_info(target)
        except Exception:
            return {"status": "unverified", "reason": "live controller identity read failed"}
        if not isinstance(info, dict):
            return {"status": "unverified", "reason": "live controller identity was malformed"}
        controller = info.get("controller")
        if not isinstance(controller, dict):
            return {"status": "unverified", "reason": "live controller identity was malformed"}
        live_name = str(controller.get("name") or "").strip()
        if not live_name:
            return {
                "status": "unverified",
                "reason": "live controller did not report a name",
            }
        if exported.casefold() != live_name.casefold():
            return {
                "status": "mismatch",
                "export_controller": exported,
                "live_controller": live_name,
            }
        return {
            "status": "name_match_only",
            "export_controller": exported,
            "live_controller": live_name,
            "note": "Controller names match, but a name is not a unique hardware identity.",
        }
    if protocol == "s7":
        if not export_confirmed:
            return {
                "status": "unverified",
                "reason": "AWL/SCL has no CPU identity; operator must confirm export origin",
            }
        from iaiops.connectors.s7.ops import s7_cpu_info

        try:
            info = s7_cpu_info(target)
        except Exception:
            return {"status": "unverified", "reason": "CPU status check failed"}
        if not isinstance(info, dict):
            return {"status": "unverified", "reason": "CPU status response was malformed"}
        status = str(info.get("cpu_status") or "").strip().upper()
        if status != "RUN":
            return {
                "status": "cpu_not_running",
                "cpu_status": status if status == "STOP" else "unknown",
            }
        return {
            "status": "operator_attested",
            "cpu_status": status,
            "note": "The operator confirmed export origin; the file itself has no CPU identity.",
        }
    return {"status": "not_applicable"}


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


def read_matched(
    target: Any,
    xref: dict[str, Any],
    read: Reader | None = None,
    *,
    export_confirmed: bool = False,
) -> dict[str, Any]:
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
    identity = _identity(target, xref, export_confirmed)
    if identity["status"] not in ("name_match_only", "operator_attested", "not_applicable"):
        return {
            "points": [],
            "read_count": 0,
            "gap_count": 0,
            "not_read": len(matched),
            "identity": identity,
            "note": "No point was read: export origin or CPU state is unverified.",
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
        "identity": identity,
        "note": (
            "read_at is this host's clock when the answer arrived; the protocol carries "
            "no device timestamp. A gap is a failed or empty read and has no value."
        ),
    }


__all__ = ["MAX_LIVE_POINTS", "default_read", "read_matched"]
