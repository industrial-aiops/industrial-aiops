"""The fixed reference dataset the determinism check computes over.

Deliberately built in code from literal arithmetic rather than shipped as a data
file: a JSON fixture can be edited without anything noticing, while a change here
moves :func:`dataset_digest` and every recorded run stops matching the ones before
it. That is the property a validation record needs — the input has to be as
pinned as the output.

Nothing here reads a clock, a file, an environment variable or a random source.
Every timestamp is an offset from :data:`EPOCH`, which is a literal.

The shape is one plausible shift on one line: a run-state series with two stops
and one collection gap, the production counter that ran beside it (including a
reset, so the wrap rule is exercised), an alarm stream with a flood in it, a
measurement series for the control chart, and a small evidence bundle for the RCA
copilot. It is small enough to read and wide enough that a change to any of the
scoring paths moves a digest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

#: The one literal instant everything else is an offset from.
EPOCH = datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)

#: Name + revision of this dataset. Bump ``REVISION`` when the data changes on
#: purpose; a recorded run naming an older revision then reads as what it is —
#: a run against a different input — instead of as a failed comparison.
NAME = "iaiops-reference-shift"
REVISION = 1

#: Sampling cadence of the collected series, in seconds.
CADENCE_S = 10

#: Run-state series layout: (duration_s, running). Two hours, two stops.
_RUN_PLAN: tuple[tuple[int, bool], ...] = (
    (1800, True),  # 06:00 → 06:30 producing
    (60, False),  # 06:30 → 06:31 a minor stoppage
    (1740, True),  # 06:31 → 07:00 producing
    (600, True),  # 07:00 → 07:10 producing, but NOT sampled (see _GAP)
    (1200, True),  # 07:10 → 07:30 producing
    (900, False),  # 07:30 → 07:45 a real stop, past the minor-stoppage threshold
    (1500, True),  # 07:45 → 08:10 producing
)

#: The unsampled span, as (offset_s, offset_s) — the collector was down.
_GAP: tuple[int, int] = (3600, 4200)

#: Value the run-state tag carries while producing / stopped.
RUNNING_VALUE = "RUN"
STOPPED_VALUE = "STOP"

#: Parts per second while producing, and where the counter is reset.
_PARTS_PER_S = 0.5
_COUNTER_RESET_AT_S = 4800  # somebody zeroed the shift counter here

#: The declared ideal cycle time, in seconds per part.
IDEAL_CYCLE_TIME_S = 2.0


def _stamp(offset_s: int) -> str:
    return (EPOCH + timedelta(seconds=offset_s)).isoformat()


def _in_gap(offset_s: int) -> bool:
    return _GAP[0] < offset_s < _GAP[1]


def _running_at(offset_s: int) -> bool:
    elapsed = 0
    for duration, running in _RUN_PLAN:
        if offset_s < elapsed + duration:
            return running
        elapsed += duration
    return _RUN_PLAN[-1][1]


def total_span_s() -> int:
    """Length of the shift the dataset describes, in seconds."""
    return sum(duration for duration, _ in _RUN_PLAN)


def run_state_samples() -> list[dict[str, Any]]:
    """The run-state series: ``{ts, value}`` every :data:`CADENCE_S`, gap excluded."""
    return [
        {"ts": _stamp(t), "value": RUNNING_VALUE if _running_at(t) else STOPPED_VALUE}
        for t in range(0, total_span_s() + 1, CADENCE_S)
        if not _in_gap(t)
    ]


def _counter_at(offset_s: int) -> int:
    """Cumulative parts at ``offset_s``, restarting at the reset point."""
    produced = 0
    for t in range(0, offset_s, CADENCE_S):
        if t == _COUNTER_RESET_AT_S:
            produced = 0
        if _running_at(t):
            produced += int(CADENCE_S * _PARTS_PER_S)
    return produced


def total_count_samples() -> list[dict[str, Any]]:
    """The total-count series — monotonic except across the deliberate reset."""
    return [
        {"ts": _stamp(t), "value": _counter_at(t)}
        for t in range(0, total_span_s() + 1, CADENCE_S)
        if not _in_gap(t)
    ]


def good_count_samples() -> list[dict[str, Any]]:
    """The good-count series: the total less a fixed reject every 40 parts."""
    return [
        {"ts": row["ts"], "value": int(row["value"]) - int(row["value"]) // 40}
        for row in total_count_samples()
    ]


#: Alarm stream: a quiet background plus a burst that qualifies as an ISA-18.2
#: flood, plus one source that chatters.
_ALARM_PLAN: tuple[tuple[int, str, str], ...] = (
    (120, "PT-101", "ALARM"),
    (900, "TT-204", "ALARM"),
    (1500, "FT-310", "ALARM"),
    # the burst: 14 annunciations inside four minutes, at the first stop
    *tuple((1800 + i * 17, f"CV-{400 + (i % 5)}", "ALARM") for i in range(14)),
    (2400, "PT-101", "ALARM"),
    # chatter: the same source cycling in/out
    *tuple((3000 + i * 25, "LSH-12", "ALARM" if i % 2 == 0 else "NORMAL") for i in range(12)),
    (5400, "MTR-7", "ALARM"),
    (5430, "MTR-7", "NORMAL"),
    (6600, "TT-204", "ALARM"),
)


def alarm_events() -> list[dict[str, Any]]:
    """The alarm stream as ``{ts, source, state}`` rows."""
    return [
        {"ts": _stamp(offset), "source": source, "state": state}
        for offset, source, state in _ALARM_PLAN
    ]


def measurement_series() -> list[float]:
    """A 40-point measurement series with a deliberate late upward drift."""
    # A repeating, non-monotonic base so the Western Electric run rules have
    # something to chew on, plus a drift after point 30 that rule 1 should see.
    base = (0.0, 0.4, -0.3, 0.1, -0.5, 0.6, -0.1, 0.2, -0.4, 0.3)
    out: list[float] = []
    for i in range(40):
        drift = 0.25 * (i - 29) if i >= 30 else 0.0
        out.append(round(10.0 + base[i % len(base)] + drift, 4))
    return out


#: The baseline learner refuses history shorter than a day (by design — a band
#: learned from one shift would flag the next shift's normal). So the analogue
#: tag carries its own longer, coarser series rather than the shift cadence,
#: and the learner is exercised on the path that produces a band instead of on
#: its refusal. It starts one week before :data:`EPOCH`.
ANALOGUE_SPAN_S = 3 * 86_400
ANALOGUE_CADENCE_S = 120
ANALOGUE_START_S = -7 * 86_400
ANALOGUE_TAG = "ns=2;i=41"


def analogue_samples() -> list[dict[str, Any]]:
    """A well-behaved analogue tag over three days, for the baseline learner."""
    base = (48.0, 49.5, 50.2, 51.0, 50.4, 49.1, 50.8, 51.3, 49.7, 50.0)
    return [
        {
            "ts": _stamp(ANALOGUE_START_S + t),
            "tag": ANALOGUE_TAG,
            "value": base[(t // ANALOGUE_CADENCE_S) % len(base)],
            "quality": "good",
        }
        for t in range(0, ANALOGUE_SPAN_S + 1, ANALOGUE_CADENCE_S)
    ]


def incident_window() -> dict[str, Any]:
    """The downtime window the RCA copilot is asked about (the 07:30 stop)."""
    return {"start": _stamp(INCIDENT_START_S), "end": _stamp(INCIDENT_END_S), "asset": "LINE-1"}


#: Where the line actually stopped — the 15-minute outage in :data:`_RUN_PLAN`.
INCIDENT_START_S = 5400
INCIDENT_END_S = 6300


def incident_tags() -> list[dict[str, Any]]:
    """Tag evidence around the incident, with the declared bounds it is judged against.

    Pressure falls through its alarm bound in the minute before the stop; motor
    current stays inside its band. One offender and one clean tag, so the RCA
    check covers both the scoring path and the not-scored path.
    """
    return [
        {
            "ref": ANALOGUE_TAG,
            "label": "hydraulic pressure",
            "warn_low": 48.0,
            "alarm_low": 45.0,
            "samples": [
                {"ts": _stamp(INCIDENT_START_S - 60 + i * 10), "value": round(51.0 - i * 1.4, 3)}
                for i in range(6)
            ],
        },
        {
            "ref": "ns=2;i=42",
            "label": "motor current",
            "warn_high": 30.0,
            "alarm_high": 40.0,
            "samples": [
                {"ts": _stamp(INCIDENT_START_S - 60 + i * 10), "value": round(12.0 + i * 0.05, 3)}
                for i in range(6)
            ],
        },
    ]


def dataset() -> dict[str, Any]:
    """The whole dataset as one plain dict — the thing that gets digested."""
    return {
        "name": NAME,
        "revision": REVISION,
        "epoch": EPOCH.isoformat(),
        "cadence_s": CADENCE_S,
        "span_s": total_span_s(),
        "unsampled_window": {"start": _stamp(_GAP[0]), "end": _stamp(_GAP[1])},
        "ideal_cycle_time_s": IDEAL_CYCLE_TIME_S,
        "run_state": run_state_samples(),
        "total_count": total_count_samples(),
        "good_count": good_count_samples(),
        "alarms": alarm_events(),
        "measurements": measurement_series(),
        "analogue": analogue_samples(),
        "incident_window": incident_window(),
        "incident_tags": incident_tags(),
    }


__all__ = [
    "ANALOGUE_CADENCE_S",
    "ANALOGUE_SPAN_S",
    "ANALOGUE_START_S",
    "ANALOGUE_TAG",
    "CADENCE_S",
    "INCIDENT_END_S",
    "INCIDENT_START_S",
    "EPOCH",
    "IDEAL_CYCLE_TIME_S",
    "NAME",
    "REVISION",
    "RUNNING_VALUE",
    "STOPPED_VALUE",
    "alarm_events",
    "analogue_samples",
    "dataset",
    "good_count_samples",
    "incident_tags",
    "incident_window",
    "measurement_series",
    "run_state_samples",
    "total_count_samples",
    "total_span_s",
]
