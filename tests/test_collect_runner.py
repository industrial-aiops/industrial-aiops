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
