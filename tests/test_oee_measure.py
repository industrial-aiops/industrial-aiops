"""Deriving OEE from what was actually collected — including what was not.

This is the payoff of the sequencing decision: a measured figure to put next to
the one a site keeps by hand. Public benchmarking puts that gap at 8–12 points,
because minor stoppages are too fast for a person to log.

The whole thing is worthless if it cheats, and there are two ways to cheat that
both flatter the seller:

1. **Counting a blind window as downtime.** The collector's connection dropping
   is not the line stopping. Unexplained downtime inflates the losses a vendor
   can offer to fix, so this is the tempting error.
2. **Counting idle or fault as production.** That is the status-word trap the
   tag roles close (#169); here it must stay closed end to end.

So time is sorted into THREE buckets — running, stopped, and unknown — and
unknown is never silently folded into either. Availability is computed over known
time only, and the coverage is reported next to it so nobody reads 62% without
learning it was measured over two thirds of the window.
"""

from __future__ import annotations

from datetime import UTC

import pytest

from iaiops.core.brain.oee_measure import (
    DEFAULT_MINOR_STOP_S,
    MIN_COVERAGE_PCT,
    measure_availability,
)
from iaiops.core.runtime.config import MonitorTag, TagRole

pytestmark = pytest.mark.unit


RUN = MonitorTag(ref="40001", role=TagRole.RUN_STATE, running_when=(2,))


def series(*pairs):
    """``(second, state)`` → the store's sample shape."""
    return [{"ts": f"2026-08-01T00:{s // 60:02d}:{s % 60:02d}+00:00", "value": v} for s, v in pairs]


def steady(state, start, end, step=1):
    return [(s, state) for s in range(start, end, step)]


class TestTheThreeBuckets:
    def test_a_line_that_ran_throughout_is_fully_available(self):
        result = measure_availability(series(*steady(2, 0, 600)), RUN)
        assert result["availability"] == pytest.approx(1.0)
        assert result["stopped_s"] == 0

    def test_a_stop_is_measured_from_the_declared_running_value(self):
        rows = series(*(steady(2, 0, 300) + steady(3, 300, 420) + steady(2, 420, 600)))
        result = measure_availability(rows, RUN)
        assert result["stopped_s"] == pytest.approx(120, abs=2)

    def test_idle_and_fault_are_not_production(self):
        """The status-word trap, verified end to end rather than only at the
        config boundary: 0=stopped 1=idle 2=running 3=fault."""
        rows = series(*(steady(2, 0, 300) + steady(1, 300, 450) + steady(3, 450, 600)))
        result = measure_availability(rows, RUN)
        assert result["running_s"] == pytest.approx(300, abs=2)
        assert result["stopped_s"] == pytest.approx(300, abs=2)


class TestABlindWindowIsNotDowntime:
    def test_a_hole_in_the_samples_becomes_unknown_not_stopped(self):
        """The tempting error, refused. A dropped connection is not a stoppage."""
        rows = series(*(steady(2, 0, 300) + steady(2, 450, 600)))
        result = measure_availability(rows, RUN)
        assert result["unknown_s"] > 100
        assert result["stopped_s"] == 0

    def test_availability_is_computed_over_known_time_only(self):
        """Otherwise a flaky network quietly becomes a productivity problem."""
        rows = series(*(steady(2, 0, 300) + steady(2, 450, 600)))
        result = measure_availability(rows, RUN)
        assert result["availability"] == pytest.approx(1.0)

    def test_coverage_travels_with_the_number(self):
        rows = series(*(steady(2, 0, 300) + steady(2, 450, 600)))
        result = measure_availability(rows, RUN)
        assert 50 < result["coverage_pct"] < 90
        assert "coverage" in result["note"].lower()

    def test_thin_coverage_refuses_to_report_an_availability(self):
        """Below the floor the figure is not conservative, it is meaningless —
        and a meaningless number that looks precise is the thing this product
        exists not to produce."""
        rows = series(*(steady(2, 0, 30) + steady(2, 3570, 3600)))
        result = measure_availability(rows, RUN)
        assert result["status"] == "insufficient_coverage"
        assert result["availability"] is None
        assert f"{MIN_COVERAGE_PCT:g}%" in result["note"]

    def test_the_refusal_still_reports_what_it_did_see(self):
        """A refusal that hides its evidence cannot be argued with."""
        rows = series(*(steady(2, 0, 30) + steady(2, 3570, 3600)))
        result = measure_availability(rows, RUN)
        assert result["running_s"] > 0 and result["unknown_s"] > 0


class TestRealCollectionJitters:
    """Samples never arrive on an exact cadence. A network hiccup, a busy PLC or
    the GIL will stretch one interval, and if that counted as a blind window the
    coverage of every real run would collapse into noise — leaving the tool
    unable to report on precisely the sites it is meant for.

    So the blind threshold is a MULTIPLE of the observed cadence, not the cadence
    itself. These tests exist because a perfectly regular fixture cannot tell the
    difference, and the first mutation run proved it: tightening the threshold to
    1× broke nothing.
    """

    def _jittered(self, count=300, base=1.0, hiccup=2.2, every=10):
        """Mostly on time, with an occasional stretched interval.

        The jitter is ASYMMETRIC on purpose. A symmetric sawtooth (0.6, 1.4,
        0.6 …) puts the MEDIAN at the high end, so no interval can exceed it and
        a too-tight threshold stays invisible — which is exactly how the first
        version of this test passed against a broken implementation. Real
        collection behaves this way too: mostly punctual, occasionally delayed.

        Deterministic — no RNG, so a failure reproduces exactly.
        """
        from datetime import datetime, timedelta

        start = datetime(2026, 8, 1, tzinfo=UTC)
        rows, offset = [], 0.0
        for i in range(count):
            offset += hiccup if i and i % every == 0 else base
            rows.append({"ts": (start + timedelta(seconds=offset)).isoformat(), "value": 2})
        return rows

    def test_ordinary_jitter_does_not_manufacture_blind_windows(self):
        result = measure_availability(self._jittered(), RUN)
        assert result["status"] == "ok"
        assert result["unknown_s"] == 0, "jitter was mistaken for a lost connection"
        assert result["coverage_pct"] == 100.0

    def test_a_real_disconnection_is_still_caught_through_the_jitter(self):
        """The threshold must stay loose enough for jitter and tight enough for
        an outage — a test that only proved the first would be worse than none."""
        from datetime import datetime, timedelta

        rows = self._jittered(count=120)
        last = datetime.fromisoformat(rows[-1]["ts"])
        for i in range(120):
            rows.append({"ts": (last + timedelta(seconds=600 + i)).isoformat(), "value": 2})
        result = measure_availability(rows, RUN)
        assert result["unknown_s"] > 500

    def test_the_cadence_it_measured_is_reported(self):
        """So a suspicious coverage figure can be traced to the rate behind it."""
        result = measure_availability(self._jittered(), RUN)
        assert result["sample_cadence_s"] == pytest.approx(1.0, abs=0.5)


class TestMinorStoppagesAreTheHeadline:
    def test_short_stops_are_counted_separately(self):
        """The ones a person never logs — and the reason a hand-kept figure
        reads high."""
        rows = series(
            *(
                steady(2, 0, 100)
                + steady(0, 100, 120)  # 20s — minor
                + steady(2, 120, 300)
                + steady(0, 300, 315)  # 15s — minor
                + steady(2, 315, 600)
            )
        )
        result = measure_availability(rows, RUN)
        assert result["minor_stops"] == 2
        assert result["minor_stop_s"] == pytest.approx(35, abs=3)

    def test_a_long_stop_is_not_a_minor_one(self):
        rows = series(*(steady(2, 0, 100) + steady(0, 100, 500) + steady(2, 500, 600)))
        result = measure_availability(rows, RUN)
        assert result["minor_stops"] == 0
        assert result["stopped_s"] == pytest.approx(400, abs=3)

    def test_the_threshold_is_stated_not_implied(self):
        result = measure_availability(series(*steady(2, 0, 600)), RUN)
        assert result["minor_stop_threshold_s"] == DEFAULT_MINOR_STOP_S

    def test_minor_stops_are_included_in_stopped_time(self):
        """They are a real availability loss, not a separate category — the
        point is that they are INVISIBLE to a manual count, not that they are
        somehow not downtime."""
        rows = series(*(steady(2, 0, 100) + steady(0, 100, 130) + steady(2, 130, 600)))
        result = measure_availability(rows, RUN)
        assert result["stopped_s"] >= result["minor_stop_s"] > 0


class TestTheComparisonThatSellsIt:
    def test_it_reports_the_gap_against_a_hand_kept_figure(self):
        from iaiops.core.brain.oee_measure import compare_to_reported

        rows = series(
            *(steady(2, 0, 400) + steady(0, 400, 430) + steady(2, 430, 580) + steady(0, 580, 600))
        )
        measured = measure_availability(rows, RUN)
        comparison = compare_to_reported(measured, reported_pct=95.0)
        assert comparison["gap_points"] > 0
        assert comparison["reported_pct"] == 95.0

    def test_the_gap_is_attributed_to_what_a_person_cannot_log(self):
        from iaiops.core.brain.oee_measure import compare_to_reported

        rows = series(*(steady(2, 0, 400) + steady(0, 400, 425) + steady(2, 425, 600)))
        comparison = compare_to_reported(measure_availability(rows, RUN), reported_pct=99.0)
        assert comparison["minor_stops"] == 1
        assert "minor" in comparison["explanation"].lower()

    def test_no_claim_is_made_when_the_measurement_was_refused(self):
        """A refused measurement must not become a sales number."""
        from iaiops.core.brain.oee_measure import compare_to_reported

        rows = series(*(steady(2, 0, 30) + steady(2, 3570, 3600)))
        comparison = compare_to_reported(measure_availability(rows, RUN), reported_pct=95.0)
        assert comparison["status"] == "insufficient_coverage"
        assert comparison["gap_points"] is None

    def test_a_measurement_above_the_reported_figure_is_reported_honestly(self):
        """It happens, and hiding it would make every other number suspect."""
        from iaiops.core.brain.oee_measure import compare_to_reported

        comparison = compare_to_reported(
            measure_availability(series(*steady(2, 0, 600)), RUN), reported_pct=80.0
        )
        assert comparison["gap_points"] < 0
        assert "higher" in comparison["explanation"].lower()


class TestItRefusesRatherThanGuesses:
    def test_a_series_too_short_to_mean_anything_is_refused(self):
        result = measure_availability(series((0, 2)), RUN)
        assert result["status"] == "insufficient_data"
        assert result["availability"] is None

    def test_a_tag_without_the_run_state_role_is_refused(self):
        counter = MonitorTag(ref="40010", role=TagRole.TOTAL_COUNT)
        with pytest.raises(ValueError, match="(?i)run_state"):
            measure_availability(series(*steady(2, 0, 600)), counter)

    def test_unparseable_timestamps_are_skipped_not_guessed(self):
        rows = series(*steady(2, 0, 600))
        rows.append({"ts": "not-a-time", "value": 2})
        result = measure_availability(rows, RUN)
        assert result["status"] == "ok"
