"""A collection plan — what to sample, how fast, and for how long.

The plan exists as a separate, validated object rather than a pile of CLI
arguments for one reason: **a run that lasts a week must be impossible to start
by accident**. Every bound is explicit, and the destructive-by-omission case
(no end) simply cannot be expressed.

This preserves the rule the connectors already follow — ``subscribe_sample``
caps at 200 samples / 60 seconds and its docstring says "never an unbounded
loop". A week-long assessment run does not break that rule; it raises the bound
and forces the operator to state it.
"""

from __future__ import annotations

import pytest

from iaiops.core.collect.plan import (
    MAX_DURATION_S,
    MIN_INTERVAL_MS,
    CollectionPlan,
    parse_duration,
)

pytestmark = pytest.mark.unit


class TestDurationIsAlwaysBounded:
    def test_a_plan_requires_a_duration(self):
        """There is no run-forever mode. A resident process on an OT network
        needs change-management approval; a run that states when it ends does
        not, and that difference is the whole deployment strategy (D21)."""
        with pytest.raises(TypeError):
            CollectionPlan(endpoint="line1", tags=("PT-204",))  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        ("text", "seconds"),
        [("30s", 30), ("5m", 300), ("2h", 7200), ("7d", 604_800), ("1w", 604_800)],
    )
    def test_human_durations_parse(self, text, seconds):
        assert parse_duration(text) == seconds

    def test_a_week_is_allowed_because_that_is_the_assessment_run(self):
        plan = CollectionPlan(endpoint="line1", tags=("PT-204",), duration_s=parse_duration("7d"))
        assert plan.duration_s == 604_800

    def test_longer_than_the_cap_is_refused_not_clamped(self):
        """Silently clamping a 30-day request to 7 days would leave an operator
        believing they had a month of history."""
        with pytest.raises(ValueError, match="(?i)duration.*cap"):
            CollectionPlan(endpoint="line1", tags=("PT-204",), duration_s=MAX_DURATION_S + 1)

    def test_a_bare_number_is_refused(self):
        """`--duration 7` is ambiguous — seven what? Refuse rather than guess."""
        with pytest.raises(ValueError, match="(?i)unit"):
            parse_duration("7")

    def test_zero_and_negative_are_refused(self):
        for bad in ("0s", "-5m"):
            with pytest.raises(ValueError):
                parse_duration(bad)


class TestSampleRateMustResolveWhatItClaims:
    def test_a_plan_states_the_shortest_stop_it_can_see(self):
        """The entire OEE case rests on catching minor stoppages. A plan that
        cannot say what it resolves cannot be checked against that claim."""
        plan = CollectionPlan(endpoint="line1", tags=("state",), duration_s=3600, interval_ms=1000)
        assert plan.resolves_stops_shorter_than_s == pytest.approx(2.0)

    def test_a_slow_rate_is_honest_about_what_it_will_miss(self):
        plan = CollectionPlan(
            endpoint="line1", tags=("state",), duration_s=3600, interval_ms=30_000
        )
        assert plan.resolves_stops_shorter_than_s == pytest.approx(60.0)
        assert "60" in plan.resolution_note

    def test_a_rate_faster_than_the_floor_is_refused(self):
        with pytest.raises(ValueError, match="(?i)interval"):
            CollectionPlan(
                endpoint="line1", tags=("t",), duration_s=60, interval_ms=MIN_INTERVAL_MS - 1
            )


class TestScopeIsExplicit:
    def test_tags_are_required(self):
        """Collecting "everything" is how a week-long run fills a disk."""
        with pytest.raises(ValueError, match="(?i)tag"):
            CollectionPlan(endpoint="line1", tags=(), duration_s=60)

    def test_the_plan_estimates_its_own_row_count_before_running(self):
        """An operator should learn the cost before the run, not after."""
        plan = CollectionPlan(endpoint="line1", tags=("a", "b"), duration_s=3600, interval_ms=1000)
        assert plan.estimated_rows == 7200

    def test_the_estimate_is_reported_in_the_summary(self):
        plan = CollectionPlan(endpoint="line1", tags=("a",), duration_s=86_400, interval_ms=1000)
        assert "86,400" in plan.summary or "86400" in plan.summary
