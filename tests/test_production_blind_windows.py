"""Parts made while the collector was blind must not inflate Performance.

`count_production` summed every positive delta. `measure_availability` excludes
blind seconds from run time. Performance is `ideal_cycle x produced / run_time`,
so crediting the parts while dropping the seconds makes the numerator describe a
longer window than the denominator — Performance rises in proportion to how blind
the run was.

Measured on a series with a 25s blind window during which the line really made
250 parts:

    old (blind steps credited): produced 1245 -> performance 1.251
    new (blind steps skipped) : produced  990 -> performance 0.995

A quarter of a factor, all upward. Higher Performance is a higher OEE, so this is
the flattering direction again — and past 100% the tool then blamed its own
input, telling the operator their cycle time or their counter must be wrong when
neither was.

Found by fixing the demo's `ideal_cycle_time_s` (it was ten times too slow and
had been printing "Performance computed to 1681.2%"), which uncovered the real
defect underneath: with an honest cycle time the demo still read 117.8%, because
its device is killed mid-run on purpose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain.oee_production import count_production, performance_factor

pytestmark = pytest.mark.unit

CADENCE_S = 0.5
PER_SAMPLE = 5  # 5 parts per 0.5s = the declared 10/s
RUN_TIME_S = 99.5  # observed time only — the blind seconds are NOT in here


def _series(gap_at: int | None = None, gap_s: float = 0.0, n: int = 200) -> list[dict]:
    """A counter series; optionally blind for ``gap_s`` while the line keeps running."""
    start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    rows, count, shift = [], 0, 0.0
    for i in range(n):
        if gap_at is not None and i == gap_at:
            shift = gap_s
            count += int(gap_s * (PER_SAMPLE / CADENCE_S))  # produced while unseen
        rows.append(
            {"ts": (start + timedelta(seconds=i * CADENCE_S + shift)).isoformat(), "value": count}
        )
        count += PER_SAMPLE
    return rows


class TestABlindStepIsNotProduction:
    def test_a_clean_window_counts_every_increment(self):
        result = count_production(_series())
        assert result["produced"] == pytest.approx(995.0)
        assert result["unobserved_steps"] == 0

    def test_the_step_across_a_blind_window_is_skipped(self):
        result = count_production(_series(gap_at=100, gap_s=25.0))
        assert result["unobserved_steps"] == 1
        assert result["produced"] == pytest.approx(990.0)

    def test_performance_stays_under_one_instead_of_reaching_125_percent(self):
        """The number that made the tool blame its own inputs."""
        blind = count_production(_series(gap_at=100, gap_s=25.0))
        perf = performance_factor(
            produced=blind["produced"], ideal_cycle_time_s=0.1, run_time_s=RUN_TIME_S
        )
        assert perf["performance"] <= 1.0

    def test_the_skipped_parts_are_reported_not_absorbed(self):
        """A count silently 250 parts short is its own kind of wrong answer."""
        note = count_production(_series(gap_at=100, gap_s=25.0))["note"]
        assert "blind window" in note
        assert "inflates Performance" in note

    def test_ordinary_jitter_is_not_a_blind_window(self):
        """Sampling jitter is normal; treating it as blindness would drop real
        production and understate the line — wrong in the other direction."""
        rows = _series()
        jittered = []
        start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
        for i, row in enumerate(rows):
            wobble = 0.15 if i % 3 else -0.1
            jittered.append(
                {
                    "ts": (start + timedelta(seconds=i * CADENCE_S + wobble)).isoformat(),
                    "value": row["value"],
                }
            )
        assert count_production(jittered)["unobserved_steps"] == 0

    def test_a_counter_reset_is_still_its_own_finding(self):
        """The blind rule must not swallow the wrap/reset rule that predates it."""
        rows = _series(n=50)
        rows.append(
            {
                "ts": (
                    datetime(2026, 8, 24, 10, 0, tzinfo=UTC) + timedelta(seconds=50 * CADENCE_S)
                ).isoformat(),
                "value": 3,
            }
        )
        result = count_production(rows)
        assert result["discontinuities"] == 1
        assert result["unobserved_steps"] == 0

    def test_the_additive_floor_carries_fast_sampling(self):
        """At 200ms the multiplicative factor alone gives 0.6s, and a 0.9s hiccup —
        ordinary on a real LAN, measured in #174/#181 — would read as blindness and
        silently discard real production. The floor is what makes fast sampling
        safe; at 0.5s cadence the two halves coincide, which is why the first
        version of this file could not tell them apart."""
        start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
        rows, count, shift = [], 0, 0.0
        for i in range(200):
            if i == 100:
                shift = 0.7  # a 0.9s interval: 3x cadence would call this blind
            rows.append(
                {"ts": (start + timedelta(seconds=i * 0.2 + shift)).isoformat(), "value": count}
            )
            count += 2
        assert count_production(rows)["unobserved_steps"] == 0

    def test_a_run_full_of_gaps_does_not_normalise_them_away(self):
        """The cadence is the MEDIAN, not the mean. A mean is dragged upward by the
        very gaps it is meant to detect, so a run that dropped out repeatedly would
        raise its own threshold until the later outages stopped counting — and
        every uncounted outage credits parts without time."""
        start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
        rows, count, shift = [], 0, 0.0
        for i in range(200):
            if i and i % 40 == 0:
                shift += 20.0
                count += 200
            rows.append(
                {
                    "ts": (start + timedelta(seconds=i * CADENCE_S + shift)).isoformat(),
                    "value": count,
                }
            )
            count += PER_SAMPLE
        assert count_production(rows)["unobserved_steps"] == 4

    def test_a_slow_cadence_still_tolerates_three_intervals(self):
        """At 1s the additive floor alone gives 2.0s while the factor gives 3.0s.
        A 2.5s hiccup on a once-a-second run is a slow read, not blindness —
        calling it blind discards real production and understates the line."""
        start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
        rows, count, shift = [], 0, 0.0
        for i in range(60):
            if i == 30:
                shift = 1.5  # a 2.5s interval
            rows.append(
                {"ts": (start + timedelta(seconds=i * 1.0 + shift)).isoformat(), "value": count}
            )
            count += 10
        assert count_production(rows)["unobserved_steps"] == 0

    def test_the_two_paths_agree_about_what_blind_means(self):
        """A counter window and a run-state window that drew the line in different
        places would silently mismatch Performance's numerator and denominator.

        Compared on a series WITH OUTLIERS, not a uniform one: the two agree
        trivially when every interval is identical, and the property being pinned
        is that both take the MEDIAN — a mean is dragged upward by the very gaps
        it exists to detect, raising its own threshold until later outages stop
        counting."""
        from iaiops.core.brain.oee_measure import GAP_FACTOR, GAP_FLOOR_S, _cadence
        from iaiops.core.brain.oee_production import _gap_limit

        start = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
        offsets, shift = [], 0.0
        for i in range(40):
            if i and i % 10 == 0:
                shift += 15.0
            offsets.append(i * CADENCE_S + shift)
        counter_rows = [(start + timedelta(seconds=o), 0.0) for o in offsets]
        state_rows = [(start + timedelta(seconds=o), True) for o in offsets]

        cadence = _cadence(state_rows)
        assert _gap_limit(counter_rows) == pytest.approx(
            max(cadence * GAP_FACTOR, cadence + GAP_FLOOR_S)
        )
