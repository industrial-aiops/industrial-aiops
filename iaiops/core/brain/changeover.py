"""Changeover / SMED analysis — setup durations between products (pure).

The discrete-manufacturing question OEE's availability number aggregates but does
not break out: *how long are our changeovers, and which are the worst?* A
changeover is the gap between the **last good part of one product** and the
**first good part of the next** — the setup/adjustment time SMED sets out to
shrink. From a stream of good-part completions stamped with their product it
measures each changeover, ranks the longest, and totals the lost time.

Pure function over injected good-part records; read-only and advisory, every
duration cited by the two timestamps that bound it.
"""

from __future__ import annotations

from datetime import datetime

MAX_ROWS = 50


def changeover_analysis(good_parts: list[dict]) -> dict:
    """[READ] Measure changeovers between products from good-part completions.

    ``good_parts`` are ``{timestamp, product}`` — one per good part, in any order
    (they are sorted by time). A changeover is recorded at each product
    transition: its duration is the time from the last good part of the outgoing
    product to the first good part of the incoming one. Returns each changeover,
    the longest, the average and total changeover time, worst-first. Every
    duration is cited by its bounding timestamps.
    """
    parsed = sorted(
        (p for p in (_parse(g) for g in (good_parts or [])) if p is not None),
        key=lambda p: p[0],
    )
    ignored = len([g for g in (good_parts or []) if isinstance(g, dict)]) - len(parsed)
    changeovers = _changeovers(parsed)
    if not changeovers:
        return {
            "good_parts": len(parsed),
            "ignored": ignored,
            "changeover_count": 0,
            "changeovers": [],
            "longest": None,
            "avgDurationS": None,
            "totalChangeoverS": None,
            "note": _NOTE,
        }

    durations = [c["durationS"] for c in changeovers]
    ranked = sorted(changeovers, key=lambda c: c["durationS"], reverse=True)
    return {
        "good_parts": len(parsed),
        "ignored": ignored,
        "changeover_count": len(changeovers),
        "changeovers": ranked[:MAX_ROWS],
        "longest": ranked[0],
        "avgDurationS": round(sum(durations) / len(durations), 1),
        "totalChangeoverS": round(sum(durations), 1),
        "note": _NOTE,
    }


_NOTE = (
    "Advisory SMED changeover analysis over injected good-part completions; each "
    "duration is the gap between the last good part of one product and the first "
    "of the next, cited by its two timestamps. Long changeovers are SMED targets."
)


def _parse(good: dict) -> tuple[datetime, str] | None:
    if not isinstance(good, dict):
        return None
    ts = _epoch(good.get("timestamp") or good.get("ts"))
    product = good.get("product") or good.get("sku")
    if ts is None or not product:
        return None
    return ts, str(product)


def _epoch(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _changeovers(parsed: list[tuple[datetime, str]]) -> list[dict]:
    """One changeover per adjacent pair whose product differs."""
    out: list[dict] = []
    for (t_a, prod_a), (t_b, prod_b) in zip(parsed, parsed[1:]):
        if prod_a != prod_b:
            out.append(
                {
                    "from": prod_a,
                    "to": prod_b,
                    "start": t_a.isoformat(),
                    "end": t_b.isoformat(),
                    "durationS": round((t_b - t_a).total_seconds(), 1),
                }
            )
    return out


__all__ = ["changeover_analysis", "MAX_ROWS"]
