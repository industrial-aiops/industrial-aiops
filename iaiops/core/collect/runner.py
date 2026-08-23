"""Run one bounded collection and report honestly on what it could not see.

The guarantee this module exists to hold: **a gap in collection is not a
stoppage.** If the collector loses its connection for ten minutes, the line may
have run perfectly throughout. Letting that silence read as downtime would
produce an OEE number that looks right and is wrong — and wrong in the
flattering direction, since unexplained downtime inflates the losses a vendor
can offer to fix.

So a run records two things: the samples it got, and the windows where it knows
it was blind. A failed read is never written as a value — not as null, not as a
repeat of the last good reading — because either would be indistinguishable from
a real sample downstream. The gaps travel with the result, and so does the
sampling resolution, so nobody reads a number without also seeing what it could
not have seen.

Time and the device are both injected, which is what lets a "week-long" run be
tested in microseconds and lets the OEE story be verified without a plant.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from iaiops.core.collect.plan import CollectionPlan

#: How a run ended. Not cosmetic: an operator reading a short assessment needs to
#: know whether it finished or was cut off.
DURATION_REACHED = "duration_reached"
STOPPED_BY_OPERATOR = "stopped_by_operator"
ITERATION_CAP = "iteration_cap"

#: Resolution of the timestamps this module writes. A run must not claim to
#: resolve stoppages finer than what it can actually record, so this is asserted
#: against the plan's minimum interval rather than left as a comment.
TIMESTAMP_RESOLUTION_S = 0.001


class _RealClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


@dataclass(frozen=True)
class RunResult:
    """What a run produced, including what it missed."""

    plan: CollectionPlan
    samples_written: int = 0
    attempted: int = 0
    gaps: tuple[dict[str, Any], ...] = ()
    elapsed_s: float = 0.0
    stopped_because: str = DURATION_REACHED
    started_at: str = ""

    @property
    def coverage_pct(self) -> float:
        """Share of intended samples actually obtained.

        Downstream analysis needs this to know whether it is looking at 100% of
        a window or 60% of it — the difference between a number and a guess.
        """
        if not self.attempted:
            return 0.0
        return round(100.0 * self.samples_written / self.attempted, 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": {
                "endpoint": self.plan.endpoint,
                "tags": list(self.plan.tags),
                "interval_ms": self.plan.interval_ms,
                "duration_s": self.plan.duration_s,
                "resolution_note": self.plan.resolution_note,
                "resolves_stops_shorter_than_s": self.plan.resolves_stops_shorter_than_s,
            },
            "started_at": self.started_at,
            "elapsed_s": round(self.elapsed_s, 2),
            "stopped_because": self.stopped_because,
            "samples_written": self.samples_written,
            "attempted": self.attempted,
            "coverage_pct": self.coverage_pct,
            "gaps": [dict(g) for g in self.gaps],
            "note": (
                "Gaps are windows where collection was blind — they are NOT downtime. "
                "Treating them as stoppages would overstate losses."
            ),
        }


@dataclass
class _GapTracker:
    """Accumulates consecutive failures into one window rather than N errors.

    Three hundred failed reads during one network outage is one gap, not three
    hundred incidents — and reporting it as three hundred would bury the signal.
    """

    gaps: list[dict[str, Any]] = field(default_factory=list)
    _open: dict[str, Any] | None = None

    def failure(self, reason: str, at: str) -> None:
        if self._open is None:
            self._open = {"from_ts": at, "to_ts": at, "samples_missed": 0, "reason": reason}
            self.gaps.append(self._open)
        self._open["to_ts"] = at
        self._open["samples_missed"] += 1

    def success(self) -> None:
        self._open = None


def _now_iso() -> str:
    """A timestamp fine enough to represent the rate we are sampling at.

    This was whole seconds, which quietly made sub-second sampling meaningless:
    at 200ms every five samples shared one stamp, the observed cadence computed
    as 0.0, and ordinary intervals were then misreported as blind windows. The
    plan meanwhile advertised resolving stoppages down to 0.4s — a claim the
    stored data could not support.

    Found against a real device over a real network, and invisible to the tests
    above because injecting the clock meant this function never ran in them.
    """
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def run_collection(
    plan: CollectionPlan,
    target: Any,
    reader: Callable[[Any, str], tuple[Any, str]],
    db_path: Any = None,
    clock: Any = None,
    should_stop: Callable[[], bool] | None = None,
    max_iterations: int | None = None,
) -> RunResult:
    """Collect ``plan`` into the local store; return what was and was not seen.

    ``reader(target, ref) -> (value, source_timestamp)`` is the cross-protocol
    read from the capability registry. Injecting it keeps this module free of
    protocol knowledge and makes the guarantees testable without a plant.
    """
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    clock = clock or _RealClock()
    started = clock.monotonic()
    deadline = started + plan.duration_s
    interval_s = plan.interval_ms / 1000.0
    tracker = _GapTracker()
    written = 0
    attempted = 0
    iterations = 0
    stopped = DURATION_REACHED

    sink = SQLiteLocalSink(
        db_path=db_path, endpoint=plan.endpoint, protocol=str(getattr(target, "protocol", ""))
    )
    try:
        while clock.monotonic() < deadline:
            if should_stop is not None and should_stop():
                stopped = STOPPED_BY_OPERATOR
                break
            if max_iterations is not None and iterations >= max_iterations:
                stopped = ITERATION_CAP
                break
            iterations += 1

            batch: list[dict] = []
            for ref in plan.tags:
                attempted += 1
                try:
                    value, source_ts = reader(target, ref)
                except Exception as exc:  # noqa: BLE001 — a blip must not end a week-long run
                    tracker.failure(f"{type(exc).__name__}: {exc}", _now_iso())
                    continue
                tracker.success()
                batch.append(
                    {
                        "metric": ref,
                        "value": value,
                        "numeric": isinstance(value, (int, float)) and not isinstance(value, bool),
                        "timestamp": source_ts or _now_iso(),
                    }
                )

            if batch:
                written += sink.write(batch)
            clock.sleep(interval_s)
    finally:
        sink.close()

    return RunResult(
        plan=plan,
        samples_written=written,
        attempted=attempted,
        gaps=tuple(tracker.gaps),
        elapsed_s=clock.monotonic() - started,
        stopped_because=stopped,
        started_at=_now_iso(),
    )


__all__ = [
    "TIMESTAMP_RESOLUTION_S",
    "RunResult",
    "run_collection",
    "DURATION_REACHED",
    "STOPPED_BY_OPERATOR",
    "ITERATION_CAP",
]
