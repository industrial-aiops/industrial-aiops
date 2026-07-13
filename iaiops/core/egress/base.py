"""Stream-egress SPI — publisher factory + point→message shaping.

A publisher exposes a uniform surface:

  * ``publish_points(points) -> int`` — publish normalized numeric points
  * ``publish_event(subject, event) -> int`` — publish one structured event (alarm / RCA verdict)
  * ``close() -> None``

Adapters (one per bus) live in sibling modules and lazy-import their client, so the base package
imports without any. The actual network delivery is isolated behind a ``_deliver(messages)`` method,
so the shaping/routing logic is fully mock-testable.
"""

from __future__ import annotations

import json
from typing import Any

from iaiops.core.brain._shared import s

MAX_MESSAGES = 100_000  # bounded batch (defensive)
SUPPORTED_PUBLISHERS = ("nats",)


class EgressError(Exception):
    """A stream-egress operation failed; carries a teaching message."""


def points_to_messages(
    points: list[dict], subject_prefix: str = "iaiops"
) -> list[tuple[str, dict]]:
    """Shape normalized numeric points into ``(subject, payload)`` messages.

    Subject: ``<prefix>.tag.<sanitized-metric>``. Payload: ``{metric, value, timestamp, tags}``.
    Non-numeric points are skipped (a bus carries live values; use a historian sink for text/state).
    """
    prefix = _sanitize_subject_token(subject_prefix) or "iaiops"
    out: list[tuple[str, dict]] = []
    for p in list(points or [])[:MAX_MESSAGES]:
        if not isinstance(p, dict) or not p.get("numeric"):
            continue
        metric = str(p.get("metric") or "")
        if not metric:
            continue
        subject = f"{prefix}.tag.{_sanitize_subject_token(metric)}"
        out.append(
            (
                subject,
                {
                    "metric": s(metric, 128),
                    "value": p.get("value"),
                    "timestamp": s(p.get("timestamp", ""), 40),
                    "tags": p.get("tags") or {},
                },
            )
        )
    return out


def encode(payload: dict) -> bytes:
    """Compact, deterministic JSON bytes for a bus message."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _sanitize_subject_token(text: str) -> str:
    """A NATS-safe subject token (no spaces / dots / wildcards inside a segment)."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(text))[:180]
    return safe.strip("_") or "unknown"


def get_publisher(kind: str, **opts: Any) -> Any:
    """Return a stream publisher for ``kind`` (nats)."""
    k = (kind or "").strip().lower()
    if k == "nats":
        from iaiops.core.egress.nats import NATSPublisher

        return NATSPublisher(**opts)
    raise EgressError(
        f"Unknown stream publisher '{kind}'. Supported: {', '.join(SUPPORTED_PUBLISHERS)}."
    )


__all__ = [
    "EgressError",
    "points_to_messages",
    "encode",
    "get_publisher",
    "SUPPORTED_PUBLISHERS",
    "MAX_MESSAGES",
]
