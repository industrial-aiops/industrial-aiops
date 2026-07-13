"""Gateway read-layer operations (READ-ONLY — no writes anywhere).

The vendor SCADA/MES platform's Gateway HTTP web API exposes the MES-ish
production surface (module health, tag tree, current tag values, active alarms,
tag-history) that the base ``opcua`` connector does not cover. These ops are all
non-destructive reads; there is no command/write path in this connector at all.

Connection details come from the tool arguments (base URL + deployment flavor),
not the YAML endpoint config — this layer is edition-scoped, not a core
protocol. The API token/key is resolved from the encrypted secret store by key
name, never passed in plaintext through a tool argument (so it never lands in
the audit log).
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.ignition.dialects import FLAVORS
from iaiops.connectors.ignition.transport import IgnitionTarget, ignition_session
from iaiops.core.brain._shared import s
from iaiops.core.runtime.config import DEFAULT_TIMEOUT_S
from iaiops.core.runtime.secretstore import SecretStoreError, get_secret

MAX_TAG_PATHS = 200


def _resolve_token(secret_name: str | None) -> str:
    """Resolve an API token/key from the encrypted secret store, or '' when unset.

    A missing/blank ``secret_name`` means "no auth" (valid for an anonymous or
    reverse-proxied gateway). A named-but-absent secret teaches rather than
    silently sending an unauthenticated request.
    """
    key = (secret_name or "").strip()
    if not key:
        return ""
    try:
        return get_secret(key)
    except SecretStoreError as exc:
        raise ValueError(
            f"Gateway API-token secret '{key}' not found in the encrypted store. "
            f"Add it with 'iaiops secret set {key}', or omit secret_name for an "
            f"unauthenticated gateway. ({s(str(exc), 120)})"
        ) from exc


def _target(
    base_url: str,
    flavor: str,
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    name: str = "ignition",
) -> IgnitionTarget:
    """Build an immutable Gateway target from tool arguments (token resolved here)."""
    return IgnitionTarget(
        name=s(name, 64) or "ignition",
        base_url=str(base_url or "").strip(),
        flavor=str(flavor or "").strip().lower() or "webdev",
        token=_resolve_token(secret_name),
        timeout_s=timeout_s,
        verify_tls=verify_tls,
    )


def _coerce(value: Any) -> Any:
    """Make a gateway value JSON-safe (scalars pass; text is bounded)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return s(value, 256)


def _clean_module(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": s(module.get("name"), 128),
        "state": s(module.get("state"), 48),
        "version": s(module.get("version"), 48),
    }


def _clean_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": s(node.get("name"), 128),
        "path": s(node.get("path"), 256),
        "type": s(node.get("type"), 48),
        "has_children": bool(node.get("has_children")),
    }


def _clean_tag(tag: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": s(tag.get("path"), 256),
        "value": _coerce(tag.get("value")),
        "quality": s(tag.get("quality"), 48),
        "timestamp": s(tag.get("timestamp"), 48),
    }


def _clean_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": s(alarm.get("name"), 128),
        "source": s(alarm.get("source"), 256),
        "priority": _coerce(alarm.get("priority")),
        "state": s(alarm.get("state"), 48),
        "label": s(alarm.get("label"), 200),
        "timestamp": s(alarm.get("timestamp"), 48),
    }


def gateway_status(
    base_url: str,
    flavor: str = "webdev",
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Gateway/module health + reachability (the Gateway doctor step)."""
    target = _target(
        base_url, flavor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with ignition_session(target) as client:
        status = client.gateway_status()
    gateway = status.get("gateway", {})
    modules = [_clean_module(m) for m in status.get("modules", [])]
    return {
        "flavor": target.flavor,
        "base_url": s(target.base_url, 128),
        "reachable": True,
        "gateway": {
            "name": s(gateway.get("name"), 128),
            "version": s(gateway.get("version"), 48),
            "state": s(gateway.get("state"), 48),
        },
        "module_count": len(modules),
        "modules": modules,
    }


def tag_browse(
    base_url: str,
    provider: str,
    path: str = "",
    flavor: str = "webdev",
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Browse the tag tree under a provider/path."""
    target = _target(
        base_url, flavor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with ignition_session(target) as client:
        nodes = client.browse(provider, path)
    return {
        "flavor": target.flavor,
        "base_url": s(target.base_url, 128),
        "provider": s(provider, 128),
        "path": s(path, 256),
        "node_count": len(nodes),
        "nodes": [_clean_node(n) for n in nodes],
    }


def tag_read(
    base_url: str,
    provider: str,
    tag_paths: list[str],
    flavor: str = "webdev",
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Current value(s)/quality/timestamp for tag path(s)."""
    paths = [str(p) for p in (tag_paths or [])][:MAX_TAG_PATHS]
    if not paths:
        return {
            "flavor": (flavor or "webdev").lower(),
            "tags": [],
            "error": "No tag_paths given.",
        }
    target = _target(
        base_url, flavor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with ignition_session(target) as client:
        tags = client.read(provider, paths)
    return {
        "flavor": target.flavor,
        "base_url": s(target.base_url, 128),
        "provider": s(provider, 128),
        "tag_count": len(tags),
        "tags": [_clean_tag(t) for t in tags],
    }


def alarm_status(
    base_url: str,
    flavor: str = "webdev",
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Active/acknowledged alarm list (normalized)."""
    target = _target(
        base_url, flavor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with ignition_session(target) as client:
        alarms = client.alarms()
    cleaned = [_clean_alarm(a) for a in alarms]
    return {
        "flavor": target.flavor,
        "base_url": s(target.base_url, 128),
        "alarm_count": len(cleaned),
        "alarms": cleaned,
    }


def tag_history(
    base_url: str,
    provider: str,
    tag_path: str,
    start: str,
    end: str,
    count: int = 100,
    flavor: str = "webdev",
    *,
    secret_name: str | None = None,
    verify_tls: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """[READ] Historian query for one tag over a time window (bounded samples)."""
    target = _target(
        base_url, flavor, secret_name=secret_name, verify_tls=verify_tls, timeout_s=timeout_s
    )
    with ignition_session(target) as client:
        samples = client.history(provider, tag_path, start, end, count)
    cleaned = [
        {
            "timestamp": s(sample.get("timestamp"), 48),
            "value": _coerce(sample.get("value")),
            "quality": s(sample.get("quality"), 48),
        }
        for sample in samples
    ]
    return {
        "flavor": target.flavor,
        "base_url": s(target.base_url, 128),
        "provider": s(provider, 128),
        "tag_path": s(tag_path, 256),
        "start": s(start, 48),
        "end": s(end, 48),
        "sample_count": len(cleaned),
        "samples": cleaned,
    }


__all__ = [
    "FLAVORS",
    "MAX_TAG_PATHS",
    "alarm_status",
    "gateway_status",
    "tag_browse",
    "tag_history",
    "tag_read",
]
