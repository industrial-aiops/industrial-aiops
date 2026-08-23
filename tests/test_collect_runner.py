"""The collection run — and the distinction the whole OEE case depends on.

**A gap in collection is not a stoppage.** If the collector loses its connection
for ten minutes, the line may have been running perfectly the whole time. Letting
that silence read as downtime would produce exactly what this product refuses to
produce: an OEE number that looks right and is wrong — and wrong in the flattering
direction, since unexplained downtime inflates the losses you can "fix".

So a run records two different things: the samples it got, and the windows where
it knows it was blind. The second is not an error log; it is data, and downstream
analysis must be able to see it.
"""

from __future__ import annotations

import pytest

from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.runner import run_collection
from iaiops.core.sink.sqlite_local import SampleFilter, query_samples, store_coverage

pytestmark = pytest.mark.unit


class FakeClock:
    """Deterministic time so a "week-long" run takes microseconds."""

    def __init__(self, step: float = 1.0):
        self.now = 1_000_000.0
        self.step = step
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds if seconds > 0 else self.step


def plan(tags=("state",), duration_s=10, interval_ms=1000):
    return CollectionPlan(
        endpoint="line1", tags=tags, duration_s=duration_s, interval_ms=interval_ms
    )


def reader_returning(*values):
    """A reader yielding the given values in order, then repeating the last."""
    seq = list(values)

    def read(_target, ref):
        value = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(value, Exception):
            raise value
        return value, ""

    return read


class TestItCollects:
    def test_samples_land_in_the_local_store(self, tmp_path):
        db = tmp_path / "d.db"
        result = run_collection(
            plan(),
            target=object(),
            reader=reader_returning(1.0),
            db_path=db,
            clock=FakeClock(),
        )
        assert result.samples_written == 10
        assert store_coverage(db)["samples"] == 10

    def test_every_configured_tag_is_sampled(self, tmp_path):
        db = tmp_path / "d.db"
        run_collection(
            plan(tags=("a", "b")),
            target=object(),
            reader=reader_returning(1.0),
            db_path=db,
            clock=FakeClock(),
        )
        assert store_coverage(db)["tags"] == 2

    def test_the_run_stops_at_its_stated_duration(self, tmp_path):
        """No run-forever mode — the bound is the deployment strategy (D21)."""
        clock = FakeClock()
        result = run_collection(
            plan(duration_s=5),
            target=object(),
            reader=reader_returning(1.0),
            db_path=tmp_path / "d.db",
            clock=clock,
        )
        assert result.elapsed_s == pytest.approx(5.0, abs=1.5)
        assert result.stopped_because == "duration_reached"


class TestAGapIsNotAStoppage:
    def test_read_failures_are_recorded_as_blind_windows(self, tmp_path):
        """The core guarantee. Silence must be visible AS silence."""
        boom = ConnectionError("PLC unreachable")
        result = run_collection(
            plan(duration_s=6),
            target=object(),
            reader=reader_returning(1.0, boom, boom, boom, 2.0, 2.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert result.gaps, "a run that lost the device must report a gap"
        assert result.gaps[0]["samples_missed"] == 3

    def test_a_gap_names_why_it_was_blind(self, tmp_path):
        result = run_collection(
            plan(duration_s=4),
            target=object(),
            reader=reader_returning(1.0, ConnectionError("PLC unreachable"), 1.0, 1.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert "unreachable" in result.gaps[0]["reason"]

    def test_gaps_are_not_written_to_the_store_as_values(self, tmp_path):
        """A failed read must never become a row. A null or a stale repeat would
        be indistinguishable from a real reading downstream."""
        db = tmp_path / "d.db"
        run_collection(
            plan(duration_s=4),
            target=object(),
            reader=reader_returning(1.0, ConnectionError("down"), ConnectionError("down"), 5.0),
            db_path=db,
            clock=FakeClock(),
        )
        rows = query_samples(SampleFilter(limit=100), db_path=db)
        assert len(rows) == 2
        assert all(r["value"] not in (None, "") for r in rows)

    def test_the_result_states_coverage_so_a_number_can_be_trusted(self, tmp_path):
        """Downstream OEE needs to know it saw 60% of the window, not 100%."""
        result = run_collection(
            plan(duration_s=10),
            target=object(),
            reader=reader_returning(*([1.0] * 6 + [ConnectionError("x")] * 4)),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert result.coverage_pct == pytest.approx(60.0, abs=0.1)

    def test_a_totally_blind_run_reports_zero_coverage_not_success(self, tmp_path):
        result = run_collection(
            plan(duration_s=3),
            target=object(),
            reader=reader_returning(ConnectionError("never came up")),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert result.coverage_pct == 0.0
        assert result.samples_written == 0
        assert result.gaps


class TestItSurvivesTheRun:
    def test_a_reader_that_raises_does_not_end_the_run(self, tmp_path):
        """A week-long run that dies on the first network blip is useless."""
        result = run_collection(
            plan(duration_s=8),
            target=object(),
            reader=reader_returning(1.0, RuntimeError("blip"), 2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert result.samples_written == 7
        assert result.stopped_because == "duration_reached"

    def test_a_stop_signal_ends_it_cleanly_and_says_so(self, tmp_path):
        calls = {"n": 0}

        def should_stop() -> bool:
            calls["n"] += 1
            return calls["n"] > 3

        result = run_collection(
            plan(duration_s=600),
            target=object(),
            reader=reader_returning(1.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            should_stop=should_stop,
        )
        assert result.stopped_because == "stopped_by_operator"
        assert result.samples_written == 3

    def test_partial_data_is_kept_when_stopped_early(self, tmp_path):
        """Interrupting an assessment must not throw away the week you got."""
        db = tmp_path / "d.db"
        run_collection(
            plan(duration_s=600),
            target=object(),
            reader=reader_returning(1.0),
            db_path=db,
            clock=FakeClock(),
            should_stop=lambda: False,
            max_iterations=5,
        )
        assert store_coverage(db)["samples"] == 5


class TestTheResultIsReportable:
    def test_it_serializes_for_both_front_ends(self, tmp_path):
        result = run_collection(
            plan(duration_s=3),
            target=object(),
            reader=reader_returning(1.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        blob = result.as_dict()
        assert {"samples_written", "coverage_pct", "gaps", "stopped_because"} <= blob.keys()

    def test_it_carries_the_plan_that_produced_it(self, tmp_path):
        result = run_collection(
            plan(duration_s=3),
            target=object(),
            reader=reader_returning(1.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert result.as_dict()["plan"]["endpoint"] == "line1"

    def test_the_resolution_limit_travels_with_the_result(self, tmp_path):
        """So nobody reads an OEE number without seeing what it could not see."""
        result = run_collection(
            plan(duration_s=3, interval_ms=5000),
            target=object(),
            reader=reader_returning(1.0),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert "10" in result.as_dict()["plan"]["resolution_note"]


class TestTimestampsResolveWhatTheRunClaims:
    """Found on real hardware, invisible to every test above.

    Injecting the clock made the loop testable — and meant the REAL timestamp
    path was never executed. The fake clock produced perfect sub-second stamps
    while the production helper truncated to whole seconds, so at 200ms every
    five samples shared one timestamp, `_cadence` computed 0.0, and ordinary
    sampling intervals were misreported as blind windows.

    The direction of that error is the familiar one: the tool CLAIMED to resolve
    stoppages down to 0.4s while storing timestamps that could not distinguish
    anything under two seconds. It looked more capable than it was.
    """

    def test_the_runners_own_timestamps_resolve_below_a_second(self):
        from iaiops.core.collect.runner import _now_iso

        stamp = _now_iso()
        seconds_field = stamp.split("T")[1].split("+")[0]
        assert "." in seconds_field, (
            f"{stamp!r} has whole-second resolution; sampling faster than 1 Hz "
            "cannot be represented and every sub-second interval collapses to zero"
        )

    def test_stamps_separated_by_a_short_sleep_differ(self):
        """A real interval shorter than the coarse format's resolution.

        Deliberately NOT "call it 200 times and expect variety": 200 calls can
        finish inside one tick on a fast machine, which made the first version of
        this test flaky for a reason that had nothing to do with the defect.
        """
        import time

        from iaiops.core.collect.runner import _now_iso

        first = _now_iso()
        time.sleep(0.02)
        assert _now_iso() != first, (
            "20ms apart and indistinguishable — sub-second sampling is unrecordable"
        )

    def test_a_fast_run_stores_distinguishable_timestamps(self, tmp_path):
        """End to end through the real stamping path, with a real (fast) clock."""
        db = tmp_path / "d.db"
        run_collection(
            plan(duration_s=1, interval_ms=50),
            target=object(),
            reader=reader_returning(1.0),
            db_path=db,
            max_iterations=6,
        )
        rows = query_samples(SampleFilter(limit=100), db_path=db)
        assert len({r["ts"] for r in rows}) > 1, (
            "every sample landed on the same timestamp — a stoppage inside that "
            "second is unmeasurable, whatever the sample rate claims"
        )

    def test_the_plans_resolution_claim_is_not_finer_than_the_stamp(self):
        """The claim and the storage must agree, or the claim is marketing."""
        from iaiops.core.collect.plan import MIN_INTERVAL_MS
        from iaiops.core.collect.runner import TIMESTAMP_RESOLUTION_S

        assert TIMESTAMP_RESOLUTION_S <= MIN_INTERVAL_MS / 1000.0
