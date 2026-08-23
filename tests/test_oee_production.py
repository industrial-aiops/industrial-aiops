"""Counting production from a PLC counter, and the trap in doing it naively.

A production counter is a register that only goes up — until it wraps, or until
somebody resets it at the start of a shift. Both look identical in the samples:
the value was 65000, then it was 3.

Getting this wrong is not a rounding error. Taking ``max - min`` across a window
containing one wrap credits the line with **~65,000 phantom parts**, sending
Performance and therefore OEE through the roof — the flattering direction again,
and by an amount nobody would question because the counter really did read those
values.

So the rule here is: **sum the positive deltas, and report the discontinuities.**
On a wrap this loses the partial increment before the rollover — at a realistic
rate, a handful of parts every few weeks — and it loses them AGAINST us. Nothing
is invented in either direction, and the discontinuity is surfaced rather than
absorbed, because "your counter was reset mid-shift" is something the person
reading the number needs to know.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.oee_production import (
    count_production,
    performance_factor,
    quality_factor,
)

pytestmark = pytest.mark.unit


def series(*values, step_s=1):
    return [
        {"ts": f"2026-08-01T00:00:{i * step_s:02d}+00:00", "value": v}
        for i, v in enumerate(values)
    ]


class TestCountingWhatWasMade:
    def test_a_monotonic_counter_counts_the_difference(self):
        assert count_production(series(100, 101, 102, 105))["produced"] == 5

    def test_a_flat_counter_produced_nothing(self):
        assert count_production(series(100, 100, 100))["produced"] == 0

    def test_a_single_sample_cannot_show_production(self):
        result = count_production(series(100))
        assert result["produced"] == 0
        assert result["status"] == "insufficient_data"

    def test_it_ignores_the_absolute_value(self):
        """Only the increments matter — a counter starting at 60000 is normal."""
        assert count_production(series(60000, 60001, 60002))["produced"] == 2


class TestAWrapDoesNotInventParts:
    def test_a_rollover_does_not_credit_sixty_five_thousand_parts(self):
        """The whole reason this module exists."""
        result = count_production(series(65530, 65533, 2, 5))
        assert result["produced"] < 20, "a wrap must not be counted as production"

    def test_the_positive_increments_around_a_wrap_are_still_counted(self):
        result = count_production(series(65530, 65533, 2, 5))
        assert result["produced"] == 6  # 3 before the wrap, 3 after

    def test_the_discontinuity_is_reported_not_absorbed(self):
        """"Your counter was reset mid-shift" is something the reader needs."""
        result = count_production(series(65530, 65533, 2, 5))
        assert result["discontinuities"] == 1
        assert "reset" in result["note"].lower() or "wrap" in result["note"].lower()

    def test_a_mid_shift_reset_is_the_same_shape_and_treated_the_same(self):
        """A wrap and a reset are indistinguishable from the samples alone, so
        neither is guessed at — both simply do not contribute."""
        result = count_production(series(400, 402, 0, 3))
        assert result["produced"] == 5
        assert result["discontinuities"] == 1

    def test_several_discontinuities_are_all_counted(self):
        result = count_production(series(10, 12, 0, 2, 0, 1))
        assert result["discontinuities"] == 2

    def test_the_loss_from_a_wrap_is_conservative(self):
        """It undercounts by the partial increment before the rollover, never
        over. Erring against ourselves is the only acceptable direction."""
        exact = count_production(series(10, 11, 12, 13))["produced"]
        wrapped = count_production(series(10, 11, 0, 1))["produced"]
        assert wrapped <= exact


class TestPerformance:
    def test_it_is_ideal_time_over_run_time(self):
        result = performance_factor(produced=100, ideal_cycle_time_s=2.0, run_time_s=250.0)
        assert result["performance"] == pytest.approx(0.8)

    def test_it_refuses_without_a_cycle_time(self):
        """Availability alone is honest; a Performance invented from a guessed
        cycle time is not."""
        result = performance_factor(produced=100, ideal_cycle_time_s=None, run_time_s=250.0)
        assert result["performance"] is None
        assert "cycle" in result["note"].lower()

    def test_it_refuses_without_run_time(self):
        assert performance_factor(produced=10, ideal_cycle_time_s=1.0, run_time_s=0)[
            "performance"
        ] is None

    def test_above_one_is_reported_raw_and_flagged(self):
        """Faster than the design cycle means the cycle time is wrong, or the
        count is. Clamping silently would hide a bad input."""
        result = performance_factor(produced=200, ideal_cycle_time_s=2.0, run_time_s=250.0)
        assert result["performance_raw"] > 1.0
        assert result["performance"] == 1.0
        assert result["warning"]


class TestQuality:
    def test_good_over_total(self):
        assert quality_factor(total=100, good=95)["quality"] == pytest.approx(0.95)

    def test_it_refuses_without_a_good_count(self):
        result = quality_factor(total=100, good=None)
        assert result["quality"] is None
        assert "good" in result["note"].lower()

    def test_good_above_total_is_refused_not_clamped(self):
        """More good parts than parts is a mapping error, and clamping it to
        100% quality would bury the one signal that says so."""
        result = quality_factor(total=100, good=120)
        assert result["quality"] is None
        assert "exceeds" in result["note"].lower()

    def test_zero_production_has_no_quality(self):
        assert quality_factor(total=0, good=0)["quality"] is None
