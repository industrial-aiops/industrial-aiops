"""Collapse ten phrasings of one fault into one row.

``alarm_bad_actors`` ranks by *source*, which is the right axis for "which
instrument is noisiest" and the wrong one for "which fault is noisiest": a plant
that words the same condition ten ways — ``PT-101 HIGH``, ``PT-102 HIGH``,
``PT-103 high alarm`` — gets ten bad actors and no clue that they are one
problem. A rationalization meeting then works the list top-down and fixes the
same thing three times.

**This clusters on exact equality of a normalized string, not on similarity.**
Case, punctuation and embedded numbers are removed; whatever remains must match
*exactly*. That is deliberately dumber than it could be, and it is the reason the
result can be trusted without a model: two messages land together only when they
are literally the same sentence with the identifiers taken out. Every cluster
carries the distinct raw texts it merged and the sources they came from, so the
merge is checkable rather than asserted — and a cluster of one is reported as a
cluster of one instead of being tidied away.

It does not claim two differently-worded alarms mean the same thing. Nothing
here decides that; a person does.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from iaiops.core.brain._shared import s

MAX_EVENTS = 20_000
MAX_CLUSTERS = 100
MAX_VARIANTS = 8
MAX_SOURCES = 12

#: Fields an event might carry its describing text in, most specific first.
TEXT_FIELDS = ("message", "description", "text", "condition", "event_type", "type", "alarm")

_DIGITS = re.compile(r"\d+")
_NON_WORD = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def event_text(event: dict) -> str:
    """The describing text of an event, or '' when it carries none."""
    for field in TEXT_FIELDS:
        raw = event.get(field)
        if isinstance(raw, str) and raw.strip():
            return s(raw, 240)
    return ""


def signature(text: str) -> str:
    """Normalized clustering key: lowercase, no digits, no punctuation.

    Digits go because ``PT-101 HIGH`` and ``PT-102 HIGH`` are one phrasing with
    two instruments in it — the instrument is already the ``source`` axis.
    """
    low = _DIGITS.sub(" ", str(text).lower())
    return " ".join(_NON_WORD.sub(" ", low).split())


def cluster_alarm_events(
    events: list[dict],
    top_n: int = 20,
    min_count: int = 1,
) -> dict[str, Any]:
    """[READ] Group alarm events by normalized message, worst cluster first.

    ``events`` are ``{source?, message|description|text|condition|type, ...}``.
    Events carrying no describing text are counted and reported separately — they
    cannot be clustered, and dropping them silently would make the shares wrong.
    """
    rows = [e for e in (events or [])[:MAX_EVENTS] if isinstance(e, dict)]
    if not rows:
        return {
            "error": "No events. Pass [{source?, message|description|condition, ...}, ...].",
        }

    buckets: dict[str, dict[str, Any]] = {}
    untexted = 0
    for event in rows:
        text = event_text(event)
        if not text:
            untexted += 1
            continue
        key = signature(text)
        if not key:
            untexted += 1
            continue
        bucket = buckets.setdefault(key, {"variants": Counter(), "sources": Counter(), "count": 0})
        bucket["count"] += 1
        bucket["variants"][text] += 1
        bucket["sources"][s(str(event.get("source", event.get("tag", "unknown"))), 96)] += 1

    clustered = sum(b["count"] for b in buckets.values())
    floor = max(1, int(min_count))
    ranked = sorted(
        (
            {
                "signature": key,
                "count": b["count"],
                "share_pct": round(100.0 * b["count"] / clustered, 2) if clustered else 0.0,
                "distinct_wordings": len(b["variants"]),
                "distinct_sources": len(b["sources"]),
                "variants": [
                    {"text": t, "count": n} for t, n in b["variants"].most_common(MAX_VARIANTS)
                ],
                "sources": [
                    {"source": src, "count": n} for src, n in b["sources"].most_common(MAX_SOURCES)
                ],
            }
            for key, b in buckets.items()
            if b["count"] >= floor
        ),
        key=lambda c: (-c["count"], c["signature"]),
    )[: max(1, min(int(top_n), MAX_CLUSTERS))]

    merged = [c for c in ranked if c["distinct_wordings"] > 1 or c["distinct_sources"] > 1]
    return {
        "events_supplied": len(rows),
        "events_clustered": clustered,
        "events_without_text": untexted,
        "cluster_count": len(buckets),
        "clusters": ranked,
        "collapsed_count": len(merged),
        "note": (
            f"{len(buckets)} event types across {clustered} clustered events. Clustering is "
            "exact equality of the message with case, punctuation and numbers removed — not "
            "similarity, and not a claim that differently-worded alarms mean the same thing. "
            "Each cluster lists the wordings and sources it merged so the merge can be checked."
            + (
                f" {untexted} event(s) carried no message text and could not be clustered; "
                "they are excluded from the shares rather than counted as one type."
                if untexted
                else ""
            )
        ),
    }


__all__ = ["MAX_EVENTS", "TEXT_FIELDS", "cluster_alarm_events", "event_text", "signature"]
