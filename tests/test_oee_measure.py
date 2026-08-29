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
from pathlib import Path

import pytest

from iaiops.cli import oee as oee_cli
from iaiops.cli.oee import _factor_line
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


class TestTheThresholdMatchesMeasuredJitter:
    """Encodes what a real device over a real LAN actually did (2026-08-23),
    so a future tuning change has to face the measurement rather than intuition.

    At a 200ms target the observed cadence was 0.283s with a worst interval of
    0.918s — **3.24x the median**. The multiplicative factor alone is 3x, so it
    would have called that ordinary interval an outage; the additive floor is
    what keeps sub-second sampling usable.
    """

    def test_the_multiplicative_factor_alone_would_be_too_tight_at_fast_rates(self):
        from iaiops.core.brain.oee_measure import GAP_FACTOR

        observed_cadence, observed_worst = 0.283, 0.918
        assert observed_worst > observed_cadence * GAP_FACTOR, (
            "the premise of the additive floor no longer holds — re-measure before removing it"
        )

    def test_the_combined_threshold_clears_the_measured_worst_case(self):
        from iaiops.core.brain.oee_measure import GAP_FACTOR, GAP_FLOOR_S

        observed_cadence, observed_worst = 0.283, 0.918
        threshold = max(observed_cadence * GAP_FACTOR, observed_cadence + GAP_FLOOR_S)
        assert threshold > observed_worst

    def test_a_slow_cadence_is_governed_by_the_factor_not_the_floor(self):
        """At 1s the measured jitter was only 1.21x, and the factor has room."""
        from iaiops.core.brain.oee_measure import GAP_FACTOR, GAP_FLOOR_S

        cadence = 1.081
        assert cadence * GAP_FACTOR > cadence + GAP_FLOOR_S
        assert cadence * GAP_FACTOR > cadence * 1.21


class TestAClampedFactorSaysSoWhereTheNumberIs:
    """`Performance 100.0%` was the ONLY thing the factor block showed.

    Measured on the lab line with a cycle time that turned out to be wrong:
    Performance computed to 494%, was clamped to 100% (deliberately — see
    `core/brain/oee.py`, OEE uses the clamped factors), and the factor block
    printed a bare 100.0%. The raw value was in the paragraph below, so it was
    not hidden; but the factor block is what gets read aloud and pasted into a
    slide, and there it was indistinguishable from a line running to spec.
    """

    def test_a_clamped_factor_carries_the_raw_value(self):
        line = _factor_line("Performance", 1.0, "note", 4.94)
        assert "100.0%" in line and "494.0%" in line

    def test_an_unclamped_factor_is_not_decorated(self):
        assert "clamped" not in _factor_line("Quality", 0.96, "note", 0.96)

    def test_a_factor_with_no_raw_counterpart_is_not_decorated(self):
        assert "clamped" not in _factor_line("Availability", 0.7688, "note", None)

    def test_an_unreported_factor_still_explains_itself(self):
        line = _factor_line("Performance", None, "No ideal cycle time declared", None)
        assert "not reported" in line and "No ideal cycle time declared" in line

    def test_the_command_does_not_format_a_factor_itself(self):
        """Structural: the defect was at the call site, not in the formatter.

        Extracting the helper is worthless if `oee_measure_cmd` keeps its own
        `{value:.1%}` — the same call-site/helper split that let a mid-word cut
        survive its own unit tests in #217.
        """
        source = Path(oee_cli.__file__).read_text("utf-8")
        body = source.split("def oee_measure_cmd(")[1].split("\ndef ")[0]
        assert "not reported" not in body, "the command renders a factor row itself"
        assert "name:13" not in body, "the command still builds the factor row template"
        # The composite OEE line is the command's own and stays there; this is
        # about the three FACTOR rows, which is where the clamp had to show.
        assert body.count(":.1%") == 1, "only the composite OEE line formats a percent"


class TestTheMeasurementWindow:
    """`oee measure` could only measure an endpoint's ENTIRE stored history.

    Found while building demo material: two collection runs on the same endpoint
    fifteen minutes apart. The second run's own coverage was 76.84%. Measuring
    reported 46.75% and refused, because the window was implicitly
    first-sample-to-last-sample and the idle gap between the runs counted as one
    enormous blind span. A site that assesses in March and again in August can
    measure neither one.

    `investigate open` already took `--start` / `--end`; the flagship number did
    not.
    """

    def _two_runs(self):
        """Ten minutes of samples, a fifty-minute gap, ten minutes more."""
        first = [
            {"ts": f"2026-08-01T09:{s // 60:02d}:{s % 60:02d}+00:00", "value": 2}
            for s in range(0, 600)
        ]
        second = [
            {"ts": f"2026-08-01T10:{s // 60:02d}:{s % 60:02d}+00:00", "value": 2}
            for s in range(0, 600)
        ]
        return first + second

    def test_without_a_window_the_idle_gap_between_runs_sinks_both(self):
        """The defect, pinned. If this ever passes cleanly the bug is back."""
        result = measure_availability(self._two_runs(), RUN)
        assert result["status"] == "insufficient_coverage"
        assert result["coverage_pct"] < 50

    def test_a_window_around_one_run_measures_that_run(self):
        result = measure_availability(
            self._two_runs(),
            RUN,
            window=("2026-08-01T09:00:00+00:00", "2026-08-01T09:09:59+00:00"),
        )
        assert result["status"] == "ok"
        assert result["availability"] == 1.0
        assert result["coverage_pct"] > 99

    def test_the_window_travels_with_the_result(self):
        result = measure_availability(
            self._two_runs(),
            RUN,
            window=("2026-08-01T09:00:00+00:00", "2026-08-01T09:09:59+00:00"),
        )
        assert result["window"] == {
            "start": "2026-08-01T09:00:00+00:00",
            "end": "2026-08-01T09:09:59+00:00",
        }
        assert "2026-08-01T09:00:00+00:00" in result["note"]

    def test_no_window_says_so_rather_than_leaving_it_implied(self):
        result = measure_availability(series(*steady(2, 0, 600)), RUN)
        assert result["window"] is None
        assert "the period the samples span" in result["note"]


class TestNarrowingCannotFlatterTheCoverage:
    """The half that makes the option safe to have.

    Filtering samples to a window WITHOUT charging for its unsampled parts would
    let anybody raise their coverage by narrowing the question to the minutes
    that happen to have data — and report "100% coverage" of a shift they saw two
    hours of. That is the flattering error this product exists to refuse, and the
    option would have introduced a fresh way to produce it.
    """

    def _ten_minutes(self):
        return [
            {"ts": f"2026-08-01T09:{s // 60:02d}:{s % 60:02d}+00:00", "value": 2}
            for s in range(0, 600)
        ]

    def test_asking_about_a_shift_you_observed_a_tenth_of_is_refused(self):
        """Ten minutes of samples, an eight-hour question."""
        result = measure_availability(
            self._ten_minutes(),
            RUN,
            window=("2026-08-01T09:00:00+00:00", "2026-08-01T17:00:00+00:00"),
        )
        assert result["status"] == "insufficient_coverage"
        assert result["coverage_pct"] < 5, "the unsampled 7h50m was not charged for"

    def test_the_unsampled_head_and_tail_become_blind_windows(self):
        result = measure_availability(
            self._ten_minutes(),
            RUN,
            window=("2026-08-01T08:00:00+00:00", "2026-08-01T10:00:00+00:00"),
        )
        blind = result["blind_windows"]
        assert len(blind) == 2, f"expected a head and a tail, got {blind}"
        assert blind[0]["start"] == "2026-08-01T08:00:00+00:00"
        assert blind[-1]["end"] == "2026-08-01T10:00:00+00:00"

    def test_blind_windows_stay_in_time_order(self):
        """The production count walks them; out of order it skips the wrong increments."""
        result = measure_availability(
            self._ten_minutes(),
            RUN,
            window=("2026-08-01T08:00:00+00:00", "2026-08-01T10:00:00+00:00"),
        )
        starts = [w["start"] for w in result["blind_windows"]]
        assert starts == sorted(starts)

    def test_a_window_that_hugs_the_samples_adds_no_phantom_blindness(self):
        """Sampling jitter at the edge is not blindness — same rule as the interior."""
        result = measure_availability(
            self._ten_minutes(),
            RUN,
            window=("2026-08-01T09:00:00+00:00", "2026-08-01T09:09:59+00:00"),
        )
        assert result["blind_windows"] == []
        assert result["coverage_pct"] > 99

    def test_a_window_with_no_samples_in_it_refuses_and_says_to_widen(self):
        result = measure_availability(
            self._ten_minutes(),
            RUN,
            window=("2026-08-02T09:00:00+00:00", "2026-08-02T17:00:00+00:00"),
        )
        assert result["status"] == "insufficient_data"
        assert "widen it" in result["note"]
        assert "2026-08-02T09:00:00+00:00" in result["note"]


class TestTheWindowIsValidated:
    def test_one_bound_alone_is_refused(self):
        with pytest.raises(ValueError, match="BOTH a start and an end"):
            measure_availability(
                series(*steady(2, 0, 600)), RUN, window=("2026-08-01T09:00:00Z", "")
            )

    def test_a_start_after_its_end_is_refused(self):
        with pytest.raises(ValueError, match="is after its end"):
            measure_availability(
                series(*steady(2, 0, 600)),
                RUN,
                window=("2026-08-01T10:00:00+00:00", "2026-08-01T09:00:00+00:00"),
            )

    def test_a_naive_bound_is_comparable_with_an_aware_sample(self):
        """The mixed-tz store this repo already had a TypeError over."""
        result = measure_availability(
            series(*steady(2, 0, 600)), RUN, window=("2026-08-01T00:00:00", "2026-08-01T00:09:59")
        )
        assert result["status"] == "ok"


class TestTheCommandPassesTheWindowOn:
    """Declaring an option is worthless if the call site drops it.

    Three defects in two days came from testing a helper and not what reaches
    it, so these go through `oee_measure_cmd` itself.
    """

    def _run(self, monkeypatch, argv, seen):
        import typer
        from typer.testing import CliRunner

        from iaiops.core.brain import oee_measure as engine

        real = engine.measure_availability

        def _spy(samples, tag, minor_stop_s=300.0, window=None):
            seen["window"] = window
            return real(samples, tag, minor_stop_s=minor_stop_s, window=window)

        monkeypatch.setattr(engine, "measure_availability", _spy)
        monkeypatch.setattr(
            oee_cli, "run_state_samples", lambda *a, **k: (RUN, series(*steady(2, 0, 600)))
        )

        class _Target:
            tags = ()
            ideal_cycle_time_s = None

        monkeypatch.setattr(
            "iaiops.core.runtime.config.load_config",
            lambda *a, **k: type("C", (), {"get_target": lambda self, n: _Target()})(),
        )
        app = typer.Typer()
        app.command()(oee_cli.oee_measure_cmd)
        return CliRunner().invoke(app, argv)

    def test_the_window_reaches_the_engine(self, monkeypatch):
        seen = {}
        self._run(
            monkeypatch,
            ["line1", "--since", "2026-08-01T00:00:00Z", "--until", "2026-08-01T00:09:59Z"],
            seen,
        )
        assert seen["window"] == ("2026-08-01T00:00:00Z", "2026-08-01T00:09:59Z")

    def test_without_the_options_the_engine_gets_no_window(self, monkeypatch):
        seen = {}
        self._run(monkeypatch, ["line1"], seen)
        assert seen["window"] is None

    @pytest.mark.parametrize(
        "argv",
        [
            ["line1", "--since", "2026-08-01T00:00:00Z"],
            ["line1", "--until", "2026-08-01T00:09:59Z"],
        ],
    )
    def test_one_bound_alone_is_refused_by_the_command(self, monkeypatch, argv):
        """One bound leaves the other end of the measured period undefined."""
        seen = {}
        result = self._run(monkeypatch, argv, seen)
        assert result.exit_code != 0
        assert "go together" in result.output
        assert "window" not in seen, "the engine was reached with half a window"


def test_the_production_count_is_scoped_to_the_same_window():
    """Availability and production are a ratio; they must agree on which seconds existed.

    Structural, because reaching this path needs a populated store. If the
    production query stopped carrying the bounds, the parts counted would come
    from the whole of history while availability came from one shift — and the
    Performance factor built from them would be nonsense that still looks like a
    percentage.
    """
    source = Path(oee_cli.__file__).read_text("utf-8")
    body = source.split("def oee_measure_cmd(")[1].split("\ndef ")[0]
    production = body.split("def _count_for(")[1].split("return counted")[0]
    assert "since=since" in production and "until=until" in production, (
        "the production query no longer carries the measurement window"
    )
