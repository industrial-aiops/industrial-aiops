"""BAS controller operations (read-first; ONE MOC-gated command).

The vendor supervisory controllers (Johnson Controls Metasys/OpenBlue REST,
Tridium Niagara oBIX/REST) aggregate many BACnet field points behind one
authenticated enterprise API. These ops sit ABOVE the ``bacnet`` field-protocol
connector: reads (point list / present value / active alarms / trend history)
are non-destructive; ``command`` is the single OT-DANGEROUS write, gated by the
governance harness and refused outright for any life-safety point.

Connection details come from the tool arguments (base URL + vendor dialect), not
the YAML endpoint config — this layer is edition-scoped, not a core protocol.
The bearer token is resolved from the encrypted secret store by key name, never
passed in plaintext through a tool argument (so it never lands in the audit log).
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.bas.dialects import VENDORS, is_life_safety
from iaiops.connectors.bas.transport import BasTarget, bas_session
from iaiops.core.brain._shared import s
from iaiops.core.runtime.config import DEFAULT_TIMEOUT_S
from iaiops.core.runtime.secretstore import SecretStoreError, get_secret

MAX_POINT_IDS = 200


def _resolve_token(secret_name: str | None) -> str:
    """Resolve a bearer token from the encrypted secret store, or '' when unset.

    A missing/blank ``secret_name`` means "no auth" (valid for an anonymous or
    reverse-proxied controller). A named-but-absent secret teaches rather than
    silently sending an unauthenticated request.
    """
    key = (secret_name or "").strip()
    if not key:
        return ""
    try:
        return get_secret(key)
    except SecretStoreError as exc:
        raise ValueError(
            f"BAS bearer token secret '{key}' not found in the encrypted store. "
            f"Add it with 'iaiops secret set {key}', or omit secret_name for an "
            f"unauthenticated controller. ({s(str(exc), 120)})"
        ) from exc


def _target(
    base_url: str,
    vendor: str,
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    name: str = "bas",
) -> BasTarget:
    """Build an immutable BAS target from tool arguments (token resolved here)."""
    return BasTarget(
        name=s(name, 64) or "bas",
        base_url=str(base_url or "").strip(),
        vendor=str(vendor or "").strip().lower(),
        token=_resolve_token(secret_name),
        timeout_s=timeout_s,
        verify_tls=verify_tls,
    )


def _clean_point(point: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a normalized point dict (device text is untrusted input)."""
    return {
        "id": s(point.get("id"), 128),
        "name": s(point.get("name"), 128),
        "value": _coerce(point.get("value")),
        "unit": s(point.get("unit"), 48),
        "status": s(point.get("status"), 48),
    }


def _coerce(value: Any) -> Any:
    """Make a controller value JSON-safe (scalars pass; text is bounded)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return s(value, 256)


def point_list(
    base_url: str,
    vendor: str,
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] List controller points/objects (normalized across vendors)."""
    target = _target(
        base_url, vendor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with bas_session(target) as client:
        points = client.list_points()
    return {
        "vendor": target.vendor,
        "base_url": s(target.base_url, 128),
        "point_count": len(points),
        "points": [_clean_point(p) for p in points],
    }


def point_read(
    base_url: str,
    vendor: str,
    point_ids: list[str],
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Present value(s) for one or more points."""
    ids = [str(p) for p in (point_ids or [])][:MAX_POINT_IDS]
    if not ids:
        return {"vendor": (vendor or "").lower(), "points": [], "error": "No point_ids given."}
    target = _target(
        base_url, vendor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with bas_session(target) as client:
        points = client.read_points(ids)
    return {
        "vendor": target.vendor,
        "base_url": s(target.base_url, 128),
        "point_count": len(points),
        "points": [_clean_point(p) for p in points],
    }


def alarm_list(
    base_url: str,
    vendor: str,
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Active alarms/events from the controller (normalized)."""
    target = _target(
        base_url, vendor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with bas_session(target) as client:
        alarms = client.list_alarms()
    cleaned = [
        {
            "id": s(a.get("id"), 128),
            "name": s(a.get("name"), 128),
            "priority": _coerce(a.get("priority")),
            "state": s(a.get("state"), 48),
            "message": s(a.get("message"), 200),
            "timestamp": s(a.get("timestamp"), 48),
        }
        for a in alarms
    ]
    return {
        "vendor": target.vendor,
        "base_url": s(target.base_url, 128),
        "alarm_count": len(cleaned),
        "alarms": cleaned,
    }


def trend_read(
    base_url: str,
    vendor: str,
    point_id: str,
    count: int = 100,
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Historical trend samples for one point (bounded)."""
    target = _target(
        base_url, vendor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with bas_session(target) as client:
        samples = client.read_trend(point_id, count)
    cleaned = [
        {"timestamp": s(sample.get("timestamp"), 48), "value": _coerce(sample.get("value"))}
        for sample in samples
    ]
    return {
        "vendor": target.vendor,
        "base_url": s(target.base_url, 128),
        "point_id": s(point_id, 128),
        "sample_count": len(cleaned),
        "samples": cleaned,
    }


def command(
    base_url: str,
    vendor: str,
    point_id: str,
    value: Any,
    *,
    point_name: str = "",
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    dry_run: bool = True,
) -> dict:
    """[WRITE][HIGH RISK] Command one controller point (off by default).

    OT-dangerous. REFUSES any life-safety point (fire/smoke/egress/pressurization)
    outright — before any network I/O. Otherwise captures the BEFORE value
    (read-back) so the write is reversible, and refuses to act unless ``dry_run``
    is explicitly False. 未经授权勿对生产控制系统写入.
    """
    denied = is_life_safety(str(point_id), str(point_name))
    if denied:
        raise ValueError(
            f"Refused: point '{s(point_id, 96)}' matches the life-safety denylist "
            f"keyword '{denied}'. bas_command must never touch fire/smoke/egress/"
            f"pressurization systems — these are life-safety systems governed by "
            f"separate codes, not a BMS setpoint. No command was sent."
        )
    target = _target(
        base_url, vendor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with bas_session(target) as client:
        try:
            before = _coerce(client.read_point(point_id).get("value"))
            read_error = ""
        except ValueError as exc:  # per-point read-back miss is data, not a crash
            before = None
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "vendor": target.vendor,
                "point_id": s(point_id, 128),
                "dry_run": True,
                "before": before,
                "would_write": _coerce(value),
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        applied = client.command(point_id, value)
    return {
        "vendor": target.vendor,
        "point_id": s(point_id, 128),
        "dry_run": False,
        "before": before,
        "written": _coerce(value),
        "applied": bool(applied),
    }


__all__ = [
    "MAX_POINT_IDS",
    "VENDORS",
    "alarm_list",
    "command",
    "point_list",
    "point_read",
    "trend_read",
]
