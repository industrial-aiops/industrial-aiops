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

from iaiops.core.brain._shared import parse_ts

#: One parser for the whole brain — see `_shared.parse_ts` for why this one
#: did not coerce naive stamps, and what that cost.
_parse = parse_ts


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


#: Same rule as the availability path (see ``oee_measure.GAP_FACTOR`` /
#: ``GAP_FLOOR_S``), applied to this series' own cadence. Duplicated as an import
#: rather than a second constant so the two paths cannot disagree about what
#: "blind" means — a counter window and a run-state window that drew the line in
#: different places would silently mismatch numerator and denominator.
def _gap_limit(rows: list[tuple[datetime, float]]) -> float:
    """The gap above which a step is treated as unobserved, from median cadence."""
    from iaiops.core.brain.oee_measure import GAP_FACTOR, GAP_FLOOR_S

    deltas = sorted((rows[i][0] - rows[i - 1][0]).total_seconds() for i in range(1, len(rows)))
    mid = len(deltas) // 2
    cadence = deltas[mid] if len(deltas) % 2 else (deltas[mid - 1] + deltas[mid]) / 2.0
    return max(cadence * GAP_FACTOR, cadence + GAP_FLOOR_S)


def _blind_spans(windows: Any) -> list[tuple[datetime, datetime]]:
    """Normalize the availability path's blind windows into comparable datetimes."""
    out: list[tuple[datetime, datetime]] = []
    for row in windows or ():
        if not isinstance(row, dict):
            continue
        start, end = parse_ts(row.get("start")), parse_ts(row.get("end"))
        if start is not None and end is not None and end > start:
            out.append((start, end))
    return out


def _overlaps(start: datetime, end: datetime, blind: list[tuple[datetime, datetime]]) -> bool:
    """Whether [start, end] touches any window the collector could not see."""
    return any(a < end and start < b for a, b in blind)


def count_production(samples: Any, blind_windows: Any = None) -> dict[str, Any]:
    """[PURE] Parts made DURING THE TIME WE WATCHED, from a counter that may wrap.

    Returns ``{produced, discontinuities, unobserved_steps, n_samples, status,
    note}``. A drop in the counter contributes NOTHING and is counted as a
    discontinuity: a wrap and a reset cannot be told apart from the samples, so
    neither is assumed.

    **An increment across a BLIND gap contributes nothing either**, and that is
    not obvious. The line kept producing while the collector could not see it,
    so those parts are real — but ``measure_availability`` excludes the blind
    seconds from run time, and Performance is ``ideal_cycle × produced /
    run_time``. Credit the parts and drop the time and the numerator describes a
    longer window than the denominator: Performance goes UP in proportion to how
    blind the run was. Measured on the demo, whose device is killed mid-run on
    purpose: 95.6% over a clean window became **117.8%** at 85% coverage — over
    100%, so the tool then warned that its own input must be wrong.

    Flattering direction, again: a higher Performance is a higher OEE. So the
    same gap rule the availability path uses is applied here, on this series'
    own cadence, and the skipped steps are reported rather than absorbed.
    """
    rows: list[tuple[datetime, float]] = []
    for row in samples or ():
        if not isinstance(row, dict):
            continue
        when = _parse(row.get("ts") or row.get("timestamp"))
        # `row.get("value", row.get("count"))` returns None for an EXPLICIT
        # `"value": None`, because the default only fires on a missing key — so a
        # row carrying its number under `count` was dropped.
        raw = row.get("value")
        value = _num(raw if raw is not None else row.get("count"))
        if when is None or value is None:
            continue
        rows.append((when, value))
    rows.sort(key=lambda r: r[0])

    if len(rows) < 2:
        return {
            "produced": 0.0,
            "discontinuities": 0,
            # Documented as always returned; this branch omitted them, so a caller
            # trusting the docstring would KeyError on the one path that matters.
            "unobserved_steps": 0,
            "unobserved_parts": 0.0,
            "n_samples": len(rows),
            "status": "insufficient_data",
            "note": "A counter needs at least two readings before it can show production.",
        }

    # TWO rules, and both are needed.
    #
    # The first version shared only the CONSTANTS and computed the cadence per
    # series, then claimed in a comment that the two paths "cannot disagree about
    # what blind means". They can: a run-state tag polled at 1s gives a 3s limit
    # while a counter polled at 10s gives 30s, so a 20s outage is blind to one and
    # ordinary to the other — parts credited, seconds excluded, the exact inflation
    # this rule exists to stop.
    #
    # But sharing the run-state THRESHOLD is wrong in the other direction: a
    # counter legitimately polled every 10s would have every single step called
    # blind by a 3s limit. The thing the two paths must share is not a threshold,
    # it is the WINDOWS the collector actually could not see — the collector reads
    # every tag in the same iteration, so an outage is common to all of them.
    #
    # So: a step is unobserved if it is a gap in THIS series (this tag alone
    # failed) OR it spans a window the availability path measured as blind
    # (everything failed). Absent the windows, only the first rule applies, which
    # is the fallback that missed the 20s outage.
    gap_limit = _gap_limit(rows)
    blind = _blind_spans(blind_windows)
    produced = 0.0
    drops = 0
    unobserved = 0
    unobserved_parts = 0.0
    for i in range(1, len(rows)):
        span = (rows[i][0] - rows[i - 1][0]).total_seconds()
        if span > gap_limit or _overlaps(rows[i - 1][0], rows[i][0], blind):
            # Blind. The parts are real; the seconds that made them are not in
            # run time, so counting them here would inflate Performance.
            unobserved += 1
            step = rows[i][1] - rows[i - 1][1]
            if step > 0:
                unobserved_parts += step
            continue
        delta = rows[i][1] - rows[i - 1][1]
        if delta >= 0:
            produced += delta
        else:
            drops += 1

    note = "Counted from rising increments only."
    if unobserved:
        note += (
            f" Those steps span {unobserved_parts:,.0f} part(s), which is how much"
            " production is NOT in the figure above."
        )
        note += (
            f" {unobserved} increment(s) spanning a blind window were NOT counted: the "
            "line kept producing but those seconds are excluded from run time, and "
            "crediting the parts without the time inflates Performance."
        )
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
        "unobserved_steps": unobserved,
        # The step COUNT alone does not tell a reader whether 1 skipped step cost
        # 3 parts or 3000.
        "unobserved_parts": round(unobserved_parts, 3),
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
