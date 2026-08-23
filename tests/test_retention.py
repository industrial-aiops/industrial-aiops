"""Retention — raw samples have a lifetime, derived facts do not.

Measured on this codebase (2026-08-23): three tags at 200ms is **2.0 GB a week**
and 102 GB a year, while the stop events derived from that same year come to
about **3 MB**. A factor of thirty-five thousand. So "what happened in March" can
be answered forever without keeping March's raw samples — which is the whole
design, and the reason continuous collection is viable on an edge box at all.

Two things make it safe rather than merely cheap:

**You cannot prune data whose value has not been extracted.** Deleting raw
samples that were never summarized loses the information permanently and
silently. So a window is prunable only once it has been SEALED — derived facts
computed and stored — and a prune that would cross an unsealed window refuses.

**A period whose raw data is gone must SAY so.** Re-deriving from whatever
fragments survived would produce a number that looks like a measurement, computed
over a fraction of the window, and quite possibly a flattering one: prune the
samples covering a stoppage and availability goes UP. Refusing is the only honest
answer, and the derived facts are there to answer with instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.retain.policy import (
    DEFAULT_RAW_DAYS,
    MIN_RAW_DAYS,
    RetentionPolicy,
)
from iaiops.core.retain.prune import plan_prune, prune
from iaiops.core.sink.sqlite_local import SQLiteLocalSink, store_coverage

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def store_with_days(tmp_path, days=30, per_day=24):
    """A store spanning ``days`` back from NOW."""
    db = tmp_path / "d.db"
    sink = SQLiteLocalSink(db_path=db, endpoint="line1", protocol="modbus")
    rows = []
    for d in range(days):
        for h in range(per_day):
            rows.append(
                {
                    "metric": "RUN",
                    "value": 2,
                    "numeric": True,
                    "timestamp": (NOW - timedelta(days=d, hours=h)).isoformat(),
                }
            )
    sink.write(rows)
    sink.close()
    return db


class TestThePolicyCannotDeleteEverything:
    def test_a_sane_default_exists(self):
        assert RetentionPolicy().raw_days == DEFAULT_RAW_DAYS

    def test_zero_days_is_refused(self):
        """ "Keep nothing" is not a retention policy, it is a data-loss switch."""
        with pytest.raises(ValueError, match="(?i)raw_days"):
            RetentionPolicy(raw_days=0)

    def test_below_the_floor_is_refused(self):
        with pytest.raises(ValueError, match=str(MIN_RAW_DAYS)):
            RetentionPolicy(raw_days=MIN_RAW_DAYS - 1)

    def test_derived_facts_have_no_expiry_and_that_is_explicit(self):
        assert RetentionPolicy().derived_days is None
        assert "never" in RetentionPolicy().summary.lower()

    def test_giving_derived_facts_an_expiry_is_refused(self):
        """Not merely unset by default — REFUSED. Derived facts are the only
        thing that can answer about a period whose raw samples have expired, so
        a later "helpful" addition of derived expiry would collapse the design
        into a store that forgets everything, slowly."""
        with pytest.raises(ValueError, match="(?i)derived"):
            RetentionPolicy(raw_days=30, derived_days=365)

    def test_the_refusal_explains_the_size_difference(self):
        """The reason is quantitative, so it can be checked rather than believed."""
        with pytest.raises(ValueError) as excinfo:
            RetentionPolicy(derived_days=90)
        assert "smaller" in str(excinfo.value)

    def test_the_summary_states_what_is_kept_and_what_is_not(self):
        text = RetentionPolicy(raw_days=14).summary
        assert "14" in text and "derived" in text.lower()


class TestNothingIsRemovedWithoutSayingSo:
    def test_planning_removes_nothing(self, tmp_path):
        db = store_with_days(tmp_path)
        before = store_coverage(db)["samples"]
        plan_prune(db, RetentionPolicy(raw_days=7), now=NOW)
        assert store_coverage(db)["samples"] == before

    def test_prune_is_a_dry_run_by_default(self, tmp_path):
        """Deleting history is irreversible; the default must not do it."""
        db = store_with_days(tmp_path)
        before = store_coverage(db)["samples"]
        result = prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=NOW)
        assert result["applied"] is False
        assert store_coverage(db)["samples"] == before

    def test_the_plan_says_how_much_and_how_far_back(self, tmp_path):
        db = store_with_days(tmp_path, days=30)
        planned = plan_prune(db, RetentionPolicy(raw_days=7), now=NOW)
        assert planned["rows_to_remove"] > 0
        assert planned["cutoff"].startswith("2026-08-16")
        assert planned["rows_to_keep"] > 0

    def test_a_store_already_inside_the_window_plans_nothing(self, tmp_path):
        db = store_with_days(tmp_path, days=3)
        assert plan_prune(db, RetentionPolicy(raw_days=7), now=NOW)["rows_to_remove"] == 0


class TestValueMustBeExtractedBeforeDeletion:
    def test_pruning_an_unsealed_window_is_refused(self, tmp_path):
        """The window was never summarized, so deleting it loses the answer
        permanently — and nothing would record that it happened."""
        db = store_with_days(tmp_path, days=30)
        result = prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=None, apply=True)
        assert result["status"] == "refused"
        assert "seal" in result["reason"].lower()
        assert store_coverage(db)["samples"] > 0

    def test_a_partially_sealed_window_prunes_only_the_sealed_part(self, tmp_path):
        db = store_with_days(tmp_path, days=30)
        sealed_to = NOW - timedelta(days=20)
        result = prune(
            db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=sealed_to, apply=True
        )
        assert result["applied"] is True
        remaining = store_coverage(db)
        assert remaining["samples"] > 0
        # Everything older than the seal point is gone; the rest survives.
        assert remaining["oldest"][:10] >= sealed_to.date().isoformat()

    def test_the_effective_cutoff_is_the_earlier_of_policy_and_seal(self, tmp_path):
        db = store_with_days(tmp_path, days=30)
        result = prune(
            db,
            RetentionPolicy(raw_days=7),
            now=NOW,
            sealed_before=NOW - timedelta(days=20),
            apply=True,
        )
        assert result["cutoff"].startswith("2026-08-03")

    def test_applying_reports_what_it_actually_removed(self, tmp_path):
        db = store_with_days(tmp_path, days=30)
        result = prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=NOW, apply=True)
        assert result["applied"] is True
        assert result["rows_removed"] > 0
        assert store_coverage(db)["samples"] == result["rows_kept"]


class TestAPrunedPeriodSaysSoRatherThanComputing:
    def test_coverage_after_pruning_reflects_reality(self, tmp_path):
        db = store_with_days(tmp_path, days=30)
        prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=NOW, apply=True)
        assert store_coverage(db)["span_days"] <= 8

    def test_asking_about_a_pruned_period_is_refused_not_estimated(self, tmp_path):
        """The flattering-error guard: prune the samples covering a stoppage and
        an availability computed from the remainder goes UP."""
        from iaiops.core.retain.prune import raw_available_from

        db = store_with_days(tmp_path, days=30)
        prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=NOW, apply=True)
        check = raw_available_from(db, NOW - timedelta(days=25))
        assert check["available"] is False
        assert "pruned" in check["reason"].lower() or "retention" in check["reason"].lower()

    def test_a_period_still_inside_the_window_is_available(self, tmp_path):
        from iaiops.core.retain.prune import raw_available_from

        db = store_with_days(tmp_path, days=30)
        prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=NOW, apply=True)
        assert raw_available_from(db, NOW - timedelta(days=2))["available"] is True

    def test_the_refusal_names_the_earliest_raw_data_that_survives(self, tmp_path):
        """So the answer is "ask me about X onwards", not just "no"."""
        from iaiops.core.retain.prune import raw_available_from

        db = store_with_days(tmp_path, days=30)
        prune(db, RetentionPolicy(raw_days=7), now=NOW, sealed_before=NOW, apply=True)
        check = raw_available_from(db, NOW - timedelta(days=25))
        assert check["earliest_raw"].startswith("2026-08-1")


class TestAnEmptyStoreIsNotAnError:
    def test_planning_against_nothing_is_fine(self, tmp_path):
        planned = plan_prune(tmp_path / "none.db", RetentionPolicy(), now=NOW)
        assert planned["rows_to_remove"] == 0

    def test_pruning_nothing_is_fine(self, tmp_path):
        result = prune(tmp_path / "none.db", RetentionPolicy(), now=NOW, sealed_before=NOW)
        assert result["rows_to_remove"] == 0
