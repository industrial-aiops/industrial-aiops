"""Production counts, and the two OEE factors that need them.

A production counter is a register that only goes up — until it wraps, or until
somebody resets it at the start of a shift. Both look identical in the samples:
the value was 65000, then it was 3.

Getting this wrong is not a rounding error. Taking ``max - min`` across a window
containing one wrap credits the line with roughly 65,000 phantom parts, sending
Performance and therefore OEE through the roof — the flattering direction again,
and by an amount nobody would question, because the counter really did read those
values.

So: **sum the positive deltas, and report the discontinuities.** On a wrap this
loses the partial increment before the rollover — at a realistic rate, a handful
of parts every few weeks — and it loses them AGAINST us. Nothing is invented in
either direction, and the discontinuity is surfaced rather than absorbed, because
"your counter was reset mid-shift" is something the person reading the number
needs to know.

The factors refuse rather than improvise. Performance without a declared cycle
time is not a conservative estimate, it is a number with a guess inside it; and
Availability alone — which needs no counter at all — already carries the headline
that minor stoppages are being missed.

[PURE] No I/O.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def count_production(samples: Any) -> dict[str, Any]:
    """[PURE] Parts made, from a counter that may wrap or be reset.

    Returns ``{produced, discontinuities, n_samples, status, note}``. A drop in
    the counter contributes NOTHING and is counted as a discontinuity: a wrap and
    a reset cannot be told apart from the samples, so neither is assumed.
    """
    rows: list[tuple[datetime, float]] = []
    for row in samples or ():
        if not isinstance(row, dict):
            continue
        when = _parse(row.get("ts") or row.get("timestamp"))
        value = _num(row.get("value", row.get("count")))
        if when is None or value is None:
            continue
        rows.append((when, value))
    rows.sort(key=lambda r: r[0])

    if len(rows) < 2:
        return {
            "produced": 0.0,
            "discontinuities": 0,
            "n_samples": len(rows),
            "status": "insufficient_data",
            "note": "A counter needs at least two readings before it can show production.",
        }

    produced = 0.0
    drops = 0
    for i in range(1, len(rows)):
        delta = rows[i][1] - rows[i - 1][1]
        if delta >= 0:
            produced += delta
        else:
            drops += 1

    note = "Counted from rising increments only."
    if drops:
        note = (
            f"{drops} discontinuity(ies): the counter went DOWN, which is either a "
            "rollover or a manual reset — indistinguishable from the samples alone, so "
            "neither was assumed and the step contributed nothing. The count is "
            "therefore slightly LOW rather than inflated by a phantom 65,000 parts."
        )
    return {
        "produced": round(produced, 3),
        "discontinuities": drops,
        "n_samples": len(rows),
        "status": "ok",
        "note": note,
    }


def performance_factor(
    produced: float,
    ideal_cycle_time_s: float | None,
    run_time_s: float,
) -> dict[str, Any]:
    """[PURE] ``(ideal_cycle x produced) / run_time`` — or an honest refusal.

    Without a declared cycle time this returns nothing rather than a plausible
    number, because a Performance built on a guessed cycle time is a guess
    wearing a percentage sign. Availability needs no counter and already carries
    the headline.
    """
    if not ideal_cycle_time_s or ideal_cycle_time_s <= 0:
        return {
            "performance": None,
            "performance_raw": None,
            "warning": "",
            "note": (
                "No ideal cycle time declared, so Performance is not reported. Add "
                "`ideal_cycle_time_s:` to the endpoint — it is a product spec, not "
                "something the machine reports, and guessing it would put a guess "
                "inside the OEE figure."
            ),
        }
    if not run_time_s or run_time_s <= 0:
        return {
            "performance": None,
            "performance_raw": None,
            "warning": "",
            "note": "No run time measured, so Performance has no denominator.",
        }

    raw = (float(ideal_cycle_time_s) * float(produced)) / float(run_time_s)
    warning = ""
    if raw > 1.0:
        warning = (
            f"Performance computed to {raw:.1%}, which is faster than the declared design "
            "cycle. Either the cycle time is wrong or the count is — the raw value is kept "
            "so the bad input is visible rather than clamped out of sight."
        )
    return {
        "performance": round(min(raw, 1.0), 4),
        "performance_raw": round(raw, 4),
        "warning": warning,
        "note": "Performance = ideal cycle x parts / run time.",
    }


def quality_factor(total: float, good: float | None) -> dict[str, Any]:
    """[PURE] ``good / total`` — refusing the cases that mean a bad mapping."""
    if good is None:
        return {
            "quality": None,
            "note": (
                "No good-count declared, so Quality is not reported. OEE covers "
                "Availability x Performance only, which is honest but partial."
            ),
        }
    if not total or total <= 0:
        return {"quality": None, "note": "No parts counted, so Quality has no denominator."}
    if float(good) > float(total):
        return {
            "quality": None,
            "note": (
                f"Good count ({good:g}) exceeds total ({total:g}). That is a mapping "
                "error — probably the wrong tag in one of the roles — and clamping it to "
                "100% would bury the one signal that says so."
            ),
        }
    return {
        "quality": round(float(good) / float(total), 4),
        "note": "Quality = good parts / total parts.",
    }


__all__ = ["count_production", "performance_factor", "quality_factor"]
