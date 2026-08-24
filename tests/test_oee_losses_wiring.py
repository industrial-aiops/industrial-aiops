"""The Six Big Losses, from measured inputs rather than five numbers by hand.

`six_big_losses` had existed since the OEE brain was written and was reachable
from nowhere: a sweep for public core functions with no production caller found
it referenced only by its own docstring and `__all__`. Four of its five inputs
are now derived by `collect` + `oee measure`, so the join is this module.

The tests that matter are the refusals and the category error:

* **No good count means no decomposition.** The shortcut — pass
  `good_count=total_count` — reports a perfect Quality factor that is
  indistinguishable in the output from a line with no rejects.
* **`minor_stop_s` is NOT the ladder's `minor_stops`.** The ladder's sits in the
  PERFORMANCE bucket (brief slowdowns while nominally running); ours is stopped
  time already inside the AVAILABILITY loss. The first version of this wiring
  passed one as the other, which double-counted the same seconds and moved loss
  out of an honest residual into a bucket that prints as classified. Caught on a
  real run: availability said 4 minor stoppages totalling 47s while the ladder
  showed `minor_stops 6s` — the clamped remains of the same seconds, in the
  wrong bucket.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.oee_losses import losses_from_measured

pytestmark = pytest.mark.unit


def _measured(**over) -> dict:
    base = {
        "status": "ok",
        "running_s": 132.4,
        "stopped_s": 47.5,
        "unknown_s": 0.0,
        "minor_stop_s": 47.5,
        "minor_stops": 4,
        "coverage_pct": 100.0,
        "availability": 0.7409,
    }
    return {**base, **over}


def _counts(produced: float) -> dict:
    return {"status": "ok", "produced": produced}


class TestAMissingInputIsNeverInvented:
    def test_no_good_count_no_decomposition(self):
        result = losses_from_measured(_measured(), _counts(1274), None, 0.1)
        assert result["status"] == "inputs_not_declared"
        assert result["missing"] == ["good count"]

    def test_the_refusal_names_the_tag_to_declare(self):
        result = losses_from_measured(_measured(), _counts(1274), None, 0.1)
        assert "role: good_count" in result["note"]

    def test_it_says_why_a_guess_would_be_worse(self):
        """The shortcut is one line away and looks harmless; the note is what
        stops the next person taking it."""
        result = losses_from_measured(_measured(), _counts(1274), None, 0.1)
        assert "perfect Quality" in result["note"]

    def test_no_ideal_cycle_no_decomposition(self):
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), None)
        assert result["status"] == "inputs_not_declared"
        assert "ideal_cycle_time_s" in result["missing"]

    def test_a_zero_ideal_cycle_counts_as_undeclared(self):
        """Zero is not a cycle time; taken literally it makes every part free."""
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0)
        assert result["status"] == "inputs_not_declared"

    def test_every_missing_input_is_listed_at_once(self):
        """Naming one at a time turns configuration into a guessing game."""
        result = losses_from_measured(_measured(), None, None, None)
        assert len(result["missing"]) == 3

    def test_an_unmeasured_window_refuses_before_anything_else(self):
        result = losses_from_measured(
            {"status": "no_running_state_matched"}, _counts(1), _counts(1), 0.1
        )
        assert result["status"] == "no_availability"


class TestTheLadderIsBuiltFromObservedTime:
    def test_planned_time_is_running_plus_stopped(self):
        """NOT the plant's schedule, which nobody has given us."""
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        assert result["planned_time_s"] == pytest.approx(179.9)
        assert result["planned_time_basis"] == "observed_known_time"

    def test_blind_time_is_excluded(self):
        """Exactly as availability excludes it. Folding it in would decompose a
        window nobody observed."""
        result = losses_from_measured(_measured(unknown_s=600.0), _counts(1274), _counts(1224), 0.1)
        assert result["planned_time_s"] == pytest.approx(179.9)

    def test_the_ladder_sums_back_to_planned(self):
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        total = sum(e["time_s"] for e in result["losses"])
        assert result["fully_productive_time_s"] + total == pytest.approx(
            result["planned_time_s"], abs=0.01
        )

    def test_the_shares_and_oee_sum_to_one(self):
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        shares = sum(e["pct_of_planned"] for e in result["losses"])
        assert shares + result["oee_from_losses"] == pytest.approx(1.0, abs=1e-6)


class TestOurMinorStopsAreNotTheLaddersMinorStops:
    def test_availability_minor_stops_do_not_reach_the_performance_bucket(self):
        """The category error. Ours is stopped time, already counted in the
        availability loss; the ladder's is a slowdown while running."""
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        minor = next(e for e in result["losses"] if e["loss"] == "minor_stops")
        assert minor["time_s"] == 0.0

    def test_the_performance_loss_stays_in_the_honest_residual(self):
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        speed = next(e for e in result["losses"] if e["loss"] == "speed_loss")
        assert speed["time_s"] > 0

    def test_nothing_is_reported_as_classified(self):
        """No split input is supplied, so no bucket may claim to be explained —
        a bucket that prints as classified says we know something we do not."""
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        assert result["fully_classified"] is False
        assert not any(e["classified"] for e in result["losses"])

    def test_the_availability_loss_is_the_whole_stopped_time(self):
        """Whatever else moves, the stopped seconds stay in availability. If the
        minor stops leaked into performance this would come up short."""
        result = losses_from_measured(_measured(), _counts(1274), _counts(1224), 0.1)
        assert result["by_bucket"]["availability"]["loss_s"] == pytest.approx(47.5, abs=0.01)
