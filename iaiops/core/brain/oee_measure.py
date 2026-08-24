"""Availability measured from collected samples — including the time it could not see.

The payoff of the OEE-first sequencing: a measured figure to set beside the one a
site keeps by hand. Public benchmarking puts that gap at 8–12 points, because
minor stoppages are too fast for a person to log.

It is worthless if it cheats, and both ways of cheating flatter the seller:

* **Counting a blind window as downtime.** A dropped connection is not a stopped
  line. Unexplained downtime inflates the losses a vendor can offer to fix, which
  makes this the tempting error rather than merely a possible one.
* **Counting idle or fault as production.** That is the PLC status-word trap the
  tag roles close, and it has to stay closed here too — this module asks the tag
  what running means and never decides for itself.

So elapsed time is sorted into THREE buckets — running, stopped, unknown — and
unknown is never folded into either. Availability is computed over KNOWN time
only, coverage is reported next to it, and below a coverage floor the figure is
withheld: a meaningless number that looks precise is exactly what this product
exists not to produce.

[PURE] No I/O. The caller supplies the samples; the CLI reads them from the local
store, following the ``baseline`` / ``baseline_store`` split.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from iaiops.core.runtime.config import MonitorTag, TagRole

#: Stops at or below this are "minor" — the ones nobody writes on a sheet, and
#: the reason a hand-kept figure reads high. Five minutes is the common
#: definition in OEE practice.
DEFAULT_MINOR_STOP_S = 300.0

#: A hole longer than ``max(cadence * GAP_FACTOR, cadence + GAP_FLOOR_S)`` is
#: treated as BLIND rather than as a state that persisted.
#:
#: Both halves are needed, and measurement rather than intuition says so.
#: Against a real Modbus device across a LAN (2026-08-23, two tags per
#: iteration):
#:
#:   ==========  ==============  ================
#:   target      median interval  worst jitter
#:   ==========  ==============  ================
#:   1000 ms     1.081 s          1.21x median
#:    200 ms     0.283 s          3.24x median
#:   ==========  ==============  ================
#:
#: Jitter as a MULTIPLE of cadence grows as the cadence approaches the cost of a
#: single read: at 200ms the network round-trip is a large share of the interval,
#: at 1s it is noise. So the multiplicative factor alone is the wrong model at
#: fast rates — 3x would have flagged that 0.918s interval as an outage — and the
#: ADDITIVE floor is what makes fast sampling safe rather than a nicety.
#:
#: ⚠️ One quiet LAN at one load level. A busier network may exceed this; if false
#: blind windows appear, measure before changing the constant.
GAP_FACTOR = 3.0

#: Additive floor, in seconds. See ``GAP_FACTOR`` — this is the half that carries
#: sub-second sampling.
GAP_FLOOR_S = 1.0

#: Below this share of known time, no availability is reported at all.
MIN_COVERAGE_PCT = 50.0
#: How many distinct run-state values to echo back when nothing matched. Enough
#: to recognise a status word (0/1/2/3), short enough that a mis-declared ANALOG
#: tag does not print a thousand readings.
MAX_OBSERVED_VALUES = 8

#: Two samples cannot describe a shift.
MIN_SAMPLES = 10


def _parse(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _rows(samples: Any, tag: MonitorTag) -> list[tuple[datetime, bool]]:
    """Timestamped run/not-run decisions, sorted. Unparseable stamps are dropped.

    The running decision is delegated to the tag, so the declared
    ``running_when`` is the only thing that decides what counts as production.
    """
    out: list[tuple[datetime, bool]] = []
    for row in samples or ():
        if not isinstance(row, dict):
            continue
        when = _parse(row.get("ts") or row.get("timestamp"))
        if when is None:
            continue
        out.append((when, tag.is_running(row.get("value", row.get("state")))))
    out.sort(key=lambda r: r[0])
    return out


def _observed(samples: Any, tag: MonitorTag) -> list[str]:
    """The distinct values the run-state tag actually carried, most common first.

    The point of the refusal above is that someone can put the declared value and
    the observed value side by side; without this list they would have to go and
    query the store themselves, which is the step nobody takes.
    """
    counts: Counter[str] = Counter()
    for row in samples or ():
        if isinstance(row, dict):
            counts[str(row.get("value", row.get("state")))] += 1
    return [value for value, _ in counts.most_common(MAX_OBSERVED_VALUES)]


def _cadence(rows: list[tuple[datetime, bool]]) -> float:
    """Median gap between samples — what the run's own rate turned out to be."""
    deltas = sorted((rows[i][0] - rows[i - 1][0]).total_seconds() for i in range(1, len(rows)))
    if not deltas:
        return 0.0
    mid = len(deltas) // 2
    return deltas[mid] if len(deltas) % 2 else (deltas[mid - 1] + deltas[mid]) / 2.0


def measure_availability(
    samples: Any,
    run_state_tag: MonitorTag,
    minor_stop_s: float = DEFAULT_MINOR_STOP_S,
) -> dict:
    """[PURE] Availability from a run-state series, honest about blind windows.

    Returns running / stopped / unknown seconds, the availability over known time,
    the coverage that produced it, and the minor stoppages — or an explicit
    refusal when there is too little to say anything.
    """
    if run_state_tag.role != TagRole.RUN_STATE:
        raise ValueError(
            f"Tag {run_state_tag.ref!r} has role {run_state_tag.role or '(none)'!r}; "
            "availability needs the tag declared as 'run_state' so that which value "
            "means running comes from the config rather than from a guess."
        )

    rows = _rows(samples, run_state_tag)
    base = {
        "tag": run_state_tag.ref,
        "running_s": 0.0,
        "stopped_s": 0.0,
        "unknown_s": 0.0,
        "minor_stops": 0,
        "minor_stop_s": 0.0,
        "minor_stop_threshold_s": minor_stop_s,
        "n_samples": len(rows),
        "availability": None,
        "coverage_pct": 0.0,
    }
    if len(rows) < MIN_SAMPLES:
        return {
            **base,
            "status": "insufficient_data",
            "note": (
                f"{len(rows)} usable samples — below {MIN_SAMPLES}. Collect first "
                "(`iaiops collect run`), then measure."
            ),
        }

    if not any(is_running for _, is_running in rows):
        # A fully-sampled run-state tag that NEVER said running is far more likely
        # a declaration that does not match what the device sends than a line that
        # stood still for the whole window. Reporting 0% availability instead is
        # the flattering reading — unexplained downtime is exactly the loss a
        # vendor then offers to fix — and it is what a `running_when: "2"` against
        # a float `2.0` produced against a real device before this check existed.
        # Refuse to give a figure and name the two values to compare.
        return {
            **base,
            "status": "no_running_state_matched",
            "observed_values": _observed(samples, run_state_tag),
            "running_when": [str(v) for v in run_state_tag.running_when],
            "note": (
                f"Tag {run_state_tag.ref!r} was sampled {len(rows)} times and NEVER "
                f"matched the declared running state "
                f"({', '.join(str(v) for v in run_state_tag.running_when) or '(none declared)'}). "
                "That is usually a declaration that does not match what the device "
                "sends — compare it with the values actually observed, listed under "
                "'observed_values'. No availability is reported: a line reads as 100% "
                "down either way, and the wrong reason is worse than no answer."
            ),
        }

    cadence = _cadence(rows)
    gap_limit = max(cadence * GAP_FACTOR, cadence + GAP_FLOOR_S)
    running = stopped = unknown = 0.0
    stops: list[float] = []
    open_stop = 0.0

    for index in range(1, len(rows)):
        span = (rows[index][0] - rows[index - 1][0]).total_seconds()
        was_running = rows[index - 1][1]
        if span > gap_limit:
            # Blind. Not a state that persisted, and emphatically not downtime.
            unknown += span
            if open_stop:
                stops.append(open_stop)
                open_stop = 0.0
            continue
        if was_running:
            running += span
            if open_stop:
                stops.append(open_stop)
                open_stop = 0.0
        else:
            stopped += span
            open_stop += span
    if open_stop:
        stops.append(open_stop)

    known = running + stopped
    total = known + unknown
    coverage = round(100.0 * known / total, 2) if total else 0.0
    minor = [s for s in stops if s <= minor_stop_s]
    result = {
        **base,
        "running_s": round(running, 1),
        "stopped_s": round(stopped, 1),
        "unknown_s": round(unknown, 1),
        "n_samples": len(rows),
        "sample_cadence_s": round(cadence, 3),
        "stops": len(stops),
        "minor_stops": len(minor),
        "minor_stop_s": round(sum(minor), 1),
        "coverage_pct": coverage,
    }

    if coverage < MIN_COVERAGE_PCT:
        return {
            **result,
            "status": "insufficient_coverage",
            "note": (
                f"Collection saw only {coverage:g}% of the window — below the "
                f"{MIN_COVERAGE_PCT:g}% floor, so no availability is reported. The blind "
                "time is NOT counted as downtime; it is simply unknown."
            ),
        }

    return {
        **result,
        "status": "ok",
        "availability": round(running / known, 4) if known else None,
        "note": (
            f"Availability is over KNOWN time ({coverage:g}% coverage); "
            f"{round(unknown, 1)}s was blind and is excluded rather than counted as "
            "downtime. Stops at or under "
            f"{minor_stop_s:g}s are counted as minor — those are the ones a manual "
            "tally cannot see."
        ),
    }


def compare_to_reported(measured: dict, reported_pct: float) -> dict:
    """Set a measured availability beside the figure a site keeps by hand.

    The comparison is the point of the whole exercise, so it must not be able to
    manufacture a favourable answer: a refused measurement produces no gap at
    all, and a measurement ABOVE the reported figure is stated as plainly as one
    below. Hiding the second would make the first suspect.
    """
    status = measured.get("status")
    if status != "ok" or measured.get("availability") is None:
        return {
            "status": status or "unknown",
            "gap_points": None,
            "reported_pct": reported_pct,
            "measured_pct": None,
            "minor_stops": measured.get("minor_stops", 0),
            "explanation": (
                "No comparison: the measurement was not reported "
                f"({status}). {measured.get('note', '')}"
            ),
        }

    measured_pct = round(100.0 * float(measured["availability"]), 2)
    gap = round(reported_pct - measured_pct, 2)
    minor_stops = int(measured.get("minor_stops", 0))
    minor_s = float(measured.get("minor_stop_s", 0.0))

    if gap > 0:
        explanation = (
            f"Measured {measured_pct:g}% against {reported_pct:g}% reported — "
            f"{gap:g} points lower. {minor_stops} minor stoppage(s) totalling "
            f"{minor_s:g}s were observed; stops that short are the ones a manual "
            "tally cannot record, which is the usual source of the gap."
        )
    elif gap < 0:
        explanation = (
            f"Measured {measured_pct:g}% against {reported_pct:g}% reported — "
            f"{abs(gap):g} points HIGHER. The measurement does not support a "
            "hidden-loss story here, and saying so is what makes the other "
            "direction credible."
        )
    else:
        explanation = f"Measured {measured_pct:g}%, matching the reported figure."

    return {
        "status": "ok",
        "gap_points": gap,
        "reported_pct": reported_pct,
        "measured_pct": measured_pct,
        "coverage_pct": measured.get("coverage_pct"),
        "minor_stops": minor_stops,
        "minor_stop_s": minor_s,
        "explanation": explanation,
    }


__all__ = [
    "measure_availability",
    "compare_to_reported",
    "DEFAULT_MINOR_STOP_S",
    "MIN_COVERAGE_PCT",
    "GAP_FACTOR",
    "GAP_FLOOR_S",
    "MIN_SAMPLES",
]
