"""One-shot approval tokens for approver-gated (dual/review tier) operations.

``iaiops approve <tool> --endpoint <ep> --by <name>`` records a short-lived
token under ``~/.iaiops/approvals/`` (0600). The ``@governed_tool`` pre-check,
when a risk tier requires a named approver, looks for a matching unexpired
token and CONSUMES it — one approval authorizes exactly one call. This
replaces the static ``OPCUA_AUDIT_APPROVED_BY`` env var pattern (still
accepted as a fallback, but audited as ``approver_source="env"``) with an
auditable, expiring, single-use grant.

Tokens are keyed by (tool name, endpoint); the file name is a SHA-256 digest
of that key so hostile endpoint strings can never traverse paths.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from iaiops.core.governance.paths import ops_path

_log = logging.getLogger("iaiops.approvals")

DEFAULT_TTL_SECONDS = 600
_APPROVALS_DIR = "approvals"


@dataclass(frozen=True)
class Approval:
    """An immutable one-shot approval grant."""

    tool: str
    endpoint: str
    approved_by: str
    created_at: float
    ttl_seconds: int
    rationale: str = ""

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl_seconds

    def is_expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) > self.expires_at


def _approvals_dir() -> Path:
    return ops_path(_APPROVALS_DIR)


def token_path(tool: str, endpoint: str) -> Path:
    """Path of the token file for (tool, endpoint) — digest-named, no traversal."""
    digest = hashlib.sha256(f"{tool}\x1f{endpoint}".encode()).hexdigest()
    return _approvals_dir() / f"{digest[:32]}.json"


def record_approval(
    tool: str,
    endpoint: str = "",
    *,
    approved_by: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    rationale: str = "",
) -> Approval:
    """Persist a one-shot approval token (0600). Returns the recorded grant.

    Raises ValueError on invalid input — approvals are a trust boundary.
    """
    if not tool or not tool.strip():
        raise ValueError("approval requires a non-empty tool name")
    if not approved_by or not approved_by.strip():
        raise ValueError("approval requires a non-empty approver name (--by)")
    if ttl_seconds <= 0:
        raise ValueError(f"approval ttl must be > 0 seconds, got {ttl_seconds}")

    approval = Approval(
        tool=tool.strip(),
        endpoint=(endpoint or "").strip(),
        approved_by=approved_by.strip(),
        created_at=time.time(),
        ttl_seconds=int(ttl_seconds),
        rationale=rationale.strip(),
    )
    directory = _approvals_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(directory, 0o700)
    except OSError as exc:
        _log.debug("Could not chmod approvals dir %s: %s", directory, exc)

    path = token_path(approval.tool, approval.endpoint)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(approval.__dict__, ensure_ascii=False), "utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    _log.info(
        "Recorded one-shot approval for %s @ %s by %s (ttl %ds)",
        approval.tool, approval.endpoint or "<any endpoint>",
        approval.approved_by, approval.ttl_seconds,
    )
    return approval


def consume_approval(tool: str, endpoint: str = "") -> Approval | None:
    """Return-and-DELETE the matching unexpired token, or None.

    One-shot: the token file is removed even when expired or corrupt, so a
    stale grant can never linger and be replayed later.
    """
    path = token_path((tool or "").strip(), (endpoint or "").strip())
    try:
        raw = path.read_text("utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        _log.warning("Could not read approval token %s: %s", path, exc)
        return None

    # Consume first (delete-on-use), then validate.
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _log.warning("Could not delete approval token %s — refusing to use it: %s", path, exc)
        return None

    try:
        data = json.loads(raw)
        approval = Approval(
            tool=str(data["tool"]),
            endpoint=str(data.get("endpoint", "")),
            approved_by=str(data["approved_by"]),
            created_at=float(data["created_at"]),
            ttl_seconds=int(data["ttl_seconds"]),
            rationale=str(data.get("rationale", "")),
        )
    except (ValueError, TypeError, KeyError) as exc:
        _log.warning("Corrupt approval token %s discarded: %s", path, exc)
        return None

    if not approval.approved_by:
        _log.warning("Approval token %s has no approver — discarded", path)
        return None
    if approval.is_expired():
        _log.warning(
            "Approval token for %s @ %s by %s EXPIRED %.0fs ago — discarded",
            approval.tool, approval.endpoint, approval.approved_by,
            time.time() - approval.expires_at,
        )
        return None
    return approval


__all__ = [
    "Approval",
    "DEFAULT_TTL_SECONDS",
    "record_approval",
    "consume_approval",
    "token_path",
]
