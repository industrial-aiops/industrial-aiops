"""Surviving an interruption — and being honest about the hole it left.

The assessment run IS the deployment strategy (D21): a week on a laptop, no
resident process, no change-management request. A week-long run that cannot
survive a closed lid is not a week-long run, and today an interruption loses
everything and starts over.

Resuming is the easy half. The half that matters is that **the time between
stopping and resuming is a blind window**, exactly like a dropped connection —
the plant kept running, we were not watching. Stitching the two halves into one
continuous series would manufacture a measurement over a window that was never
observed, and in the usual direction: a stoppage that happened while we were away
simply disappears, and availability goes up.

So the deadline is the ORIGINAL end time, not "now plus what is left". "Collect
for a week" means a week of the plant's operation; pausing for twelve hours means
you covered six and a half days, and coverage has to say so rather than quietly
extending the finish line until the sample count looks right.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.session import (
    Session,
    find_resumable,
    load_session,
    save_session,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def plan(endpoint="line1", duration_s=604_800, interval_ms=1000):
    return CollectionPlan(
        endpoint=endpoint, tags=("RUN",), duration_s=duration_s, interval_ms=interval_ms
    )


def session(started=T0, **kw):
    return Session(
        run_id=kw.pop("run_id", "r1"),
        plan=kw.pop("plan_", plan()),
        started_at=started.isoformat(),
        **kw,
    )


class TestTheDeadlineIsTheOriginalEndTime:
    def test_a_session_knows_when_it_should_finish(self):
        s = session()
        assert s.deadline == (T0 + timedelta(days=7)).isoformat()

    def test_resuming_does_not_extend_the_finish_line(self):
        """ "A week" means a week of the plant's operation, not a week of our
        uptime. Extending it until the sample count looks right would be
        measuring until the answer is convenient."""
        s = session().paused_at((T0 + timedelta(days=2)).isoformat())
        resumed = s.resumed_at((T0 + timedelta(days=3)).isoformat())
        assert resumed.deadline == s.deadline

    def test_remaining_time_shrinks_across_a_pause(self):
        s = session().paused_at((T0 + timedelta(days=2)).isoformat())
        resumed = s.resumed_at((T0 + timedelta(days=3)).isoformat())
        remaining = resumed.remaining_s(now=T0 + timedelta(days=3))
        assert remaining == pytest.approx(4 * 86400, abs=60)

    def test_a_session_past_its_deadline_has_nothing_left(self):
        s = session()
        assert s.remaining_s(now=T0 + timedelta(days=9)) == 0.0
        assert s.is_finished(now=T0 + timedelta(days=9)) is True


class TestThePauseIsABlindWindow:
    def test_a_pause_becomes_a_recorded_gap(self):
        """Not bookkeeping — the plant ran while we were away, and a stoppage in
        that window would otherwise vanish and lift availability."""
        s = session().paused_at((T0 + timedelta(days=2)).isoformat())
        resumed = s.resumed_at((T0 + timedelta(days=2, hours=12)).isoformat())
        assert len(resumed.gaps) == 1
        assert resumed.gaps[0]["reason"].lower().count("interrupt") == 1

    def test_the_gap_spans_exactly_the_time_away(self):
        s = session().paused_at((T0 + timedelta(days=2)).isoformat())
        resumed = s.resumed_at((T0 + timedelta(days=2, hours=12)).isoformat())
        gap = resumed.gaps[0]
        assert gap["from_ts"].startswith("2026-08-22T06:00")
        assert gap["to_ts"].startswith("2026-08-22T18:00")

    def test_several_interruptions_each_leave_their_own_gap(self):
        s = session()
        for day in (2, 4):
            s = s.paused_at((T0 + timedelta(days=day)).isoformat())
            s = s.resumed_at((T0 + timedelta(days=day, hours=1)).isoformat())
        assert len(s.gaps) == 2

    def test_resuming_without_a_pause_records_nothing(self):
        s = session()
        assert s.resumed_at((T0 + timedelta(days=1)).isoformat()).gaps == ()

    def test_blind_time_is_totalled_for_the_report(self):
        s = session().paused_at((T0 + timedelta(days=2)).isoformat())
        s = s.resumed_at((T0 + timedelta(days=2, hours=6)).isoformat())
        assert s.blind_s == pytest.approx(6 * 3600, abs=1)


class TestFindingSomethingToResume:
    def test_an_unfinished_session_is_resumable(self, tmp_path):
        save_session(session(), base_dir=tmp_path)
        found = find_resumable("line1", now=T0 + timedelta(days=1), base_dir=tmp_path)
        assert found is not None and found.run_id == "r1"

    def test_a_finished_session_is_not_offered(self, tmp_path):
        save_session(session(), base_dir=tmp_path)
        assert find_resumable("line1", now=T0 + timedelta(days=9), base_dir=tmp_path) is None

    def test_a_completed_session_is_not_offered_even_inside_its_window(self, tmp_path):
        save_session(session().completed(), base_dir=tmp_path)
        assert find_resumable("line1", now=T0 + timedelta(days=1), base_dir=tmp_path) is None

    def test_another_endpoints_session_is_not_offered(self, tmp_path):
        save_session(session(), base_dir=tmp_path)
        assert find_resumable("line2", now=T0 + timedelta(days=1), base_dir=tmp_path) is None

    def test_nothing_to_resume_is_not_an_error(self, tmp_path):
        assert find_resumable("line1", now=T0, base_dir=tmp_path) is None

    def test_the_newest_unfinished_session_wins(self, tmp_path):
        save_session(session(run_id="old"), base_dir=tmp_path)
        save_session(session(run_id="new", started=T0 + timedelta(hours=1)), base_dir=tmp_path)
        found = find_resumable("line1", now=T0 + timedelta(days=1), base_dir=tmp_path)
        assert found.run_id == "new"


class TestItSurvivesTheRoundTrip:
    def test_a_session_reloads_with_its_gaps(self, tmp_path):
        s = session().paused_at((T0 + timedelta(days=2)).isoformat())
        s = s.resumed_at((T0 + timedelta(days=2, hours=3)).isoformat())
        save_session(s, base_dir=tmp_path)
        again = load_session("r1", base_dir=tmp_path)
        assert len(again.gaps) == 1
        assert again.blind_s == pytest.approx(3 * 3600, abs=1)

    def test_the_plan_survives_so_a_resume_cannot_change_the_terms(self, tmp_path):
        """Resuming with a different interval would silently produce a series
        whose resolution changes half-way through."""
        save_session(session(plan_=plan(interval_ms=500)), base_dir=tmp_path)
        again = load_session("r1", base_dir=tmp_path)
        assert again.plan.interval_ms == 500
        assert again.plan.tags == ("RUN",)

    def test_the_file_is_owner_only(self, tmp_path):
        path = save_session(session(), base_dir=tmp_path)
        assert oct(path.stat().st_mode)[-3:] == "600"

    def test_a_missing_session_is_reported_clearly(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="(?i)nope"):
            load_session("nope", base_dir=tmp_path)


class TestDurationsReadAtTheirOwnScale:
    """A week-long run reads naturally in hours; a two-minute one does not.
    `f"{s/3600:.1f}h"` renders twelve seconds of blind time as "0.0h" — true,
    and misleading in the direction that makes a real gap look like nothing.
    Found by running the resume path end to end and reading the output."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0.4, "400ms"), (12, "12s"), (95, "1.6min"), (7200, "2.0h"), (604_800, "7.0d")],
    )
    def test_the_unit_matches_the_magnitude(self, seconds, expected):
        from iaiops.cli._common import humanize_seconds

        assert humanize_seconds(seconds) == expected

    def test_a_short_gap_never_renders_as_zero(self):
        from iaiops.cli._common import humanize_seconds

        for seconds in (0.5, 1, 5, 12, 45):
            assert not humanize_seconds(seconds).startswith("0.0")

    def test_negative_durations_are_clamped_rather_than_shown(self):
        from iaiops.cli._common import humanize_seconds

        assert humanize_seconds(-5) == "0ms"
