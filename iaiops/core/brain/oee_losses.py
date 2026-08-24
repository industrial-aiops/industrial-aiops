"""The Six Big Losses, assembled from what was actually measured.

``oee.six_big_losses`` has existed since the OEE brain was written and could be
reached from nowhere: a sweep for public core functions with no production caller
found it referenced only by its own docstring and ``__all__``. It takes five
numbers a person had to supply by hand, and the whole point of the collection
work is that four of them are now derived. This module is the join.

Two honesty rules shape it, and both are refusals.

**A missing input is never invented.** ``six_big_losses`` requires a good count,
and the tempting shortcut — pass ``good_count=total_count`` when no good-count tag
is declared — silently claims a PERFECT quality factor. That flatters the line,
flatters the tool, and is indistinguishable in the output from a line that really
did produce no rejects. So a site without the tag is told which tag to declare and
gets no decomposition.

**"Planned time" here is time we could SEE.** The classic ladder starts from the
plant's planned production time, which is a schedule nobody has given us. What is
derived is running + stopped — known time, with blind windows excluded exactly as
availability excludes them. That makes the losses a decomposition of the OBSERVED
window, which is a smaller and truthful claim, and the result says so rather than
letting a reader assume the schedule was consulted.

[PURE] No I/O. The caller supplies the measurement.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num
from iaiops.core.brain.oee import six_big_losses

#: What the decomposition needs, and the tag or setting that supplies it. Ordered
#: so the message names the cheapest thing to fix first.
REQUIREMENTS = (
    ("ideal_cycle_time_s", "declare `ideal_cycle_time_s:` on the endpoint — the design cycle"),
    ("total count", "declare a tag with `role: total_count`"),
    ("good count", "declare a tag with `role: good_count`"),
)


def _missing(ideal_cycle_time_s: Any, totals: Any, goods: Any) -> list[tuple[str, str]]:
    absent = []
    if not (num(ideal_cycle_time_s) or 0.0) > 0:
        absent.append(REQUIREMENTS[0])
    if not isinstance(totals, dict):
        absent.append(REQUIREMENTS[1])
    if not isinstance(goods, dict):
        absent.append(REQUIREMENTS[2])
    return absent


def losses_from_measured(
    measured: Any,
    totals: Any = None,
    goods: Any = None,
    ideal_cycle_time_s: Any = None,
) -> dict:
    """[PURE] Six Big Losses from a measured window, or a refusal naming the gap.

    ``measured`` is a :func:`~iaiops.core.brain.oee_measure.measure_availability`
    result; ``totals`` / ``goods`` are
    :func:`~iaiops.core.brain.oee_production.count_production` results for the
    total- and good-count tags.

    **No split is supplied, and the near-miss is worth naming.** The ladder's
    ``minor_stops`` sits in the PERFORMANCE bucket — brief slowdowns while the
    machine is nominally running. What ``measure_availability`` calls a minor
    stoppage is stopped time, already inside the AVAILABILITY loss. Passing one as
    the other double-counts the same seconds and moves loss out of an honest
    residual into a bucket that prints as classified, so the tool looks more
    informative than it is — caught by comparing the two numbers on a real run:
    availability reported 4 minor stoppages totalling 47s while the ladder showed
    ``minor_stops 6s``, the clamped remains of the same seconds in the wrong
    bucket.

    Breakdown and setup are not distinguishable either: a run-state tag cannot
    tell an unplanned failure from a changeover, and calling every stop a
    breakdown overstates the loss a vendor can then offer to fix. So the split
    inputs stay unsupplied and every bucket is marked unclassified rather than
    filled with a guess.
    """
    if not isinstance(measured, dict) or measured.get("status") != "ok":
        status = measured.get("status", "unavailable") if isinstance(measured, dict) else "invalid"
        return {
            "status": "no_availability",
            "note": (
                f"No availability was measured ({status}), and every loss is a share of "
                "measured time. Fix that first — the decomposition inherits its honesty "
                "from the measurement."
            ),
        }

    absent = _missing(ideal_cycle_time_s, totals, goods)
    if absent:
        return {
            "status": "inputs_not_declared",
            "missing": [name for name, _ in absent],
            "note": (
                "The Six Big Losses need "
                + ", ".join(name for name, _ in absent)
                + ". Supplying a guess instead would be worse than no answer — assuming "
                "every part was good, for instance, reports a perfect Quality factor that "
                "reads exactly like a line with no rejects. To fix: "
                + "; ".join(how for _, how in absent)
                + "."
            ),
        }

    running = num(measured.get("running_s")) or 0.0
    stopped = num(measured.get("stopped_s")) or 0.0
    result = six_big_losses(
        planned_time_s=running + stopped,
        run_time_s=running,
        ideal_cycle_time_s=num(ideal_cycle_time_s) or 0.0,
        total_count=num(totals.get("produced")) or 0.0,
        good_count=num(goods.get("produced")) or 0.0,
    )
    return {
        **result,
        "status": "ok",
        "planned_time_basis": "observed_known_time",
        "coverage_pct": measured.get("coverage_pct"),
        "note": (
            "Losses are a decomposition of OBSERVED time (running + stopped, "
            f"{measured.get('coverage_pct')}% of the window) — not of the plant's planned "
            "production schedule, which this tool has not been given. Blind windows are "
            "excluded, exactly as they are from availability. No split input is supplied "
            "— a run-state tag cannot separate a breakdown from a changeover, and the "
            "minor stoppages counted in availability are stopped time, not the ladder's "
            "in-run minor stops — so every bucket is marked unclassified rather than "
            "filled with a guess."
        ),
    }


__all__ = ["REQUIREMENTS", "losses_from_measured"]
