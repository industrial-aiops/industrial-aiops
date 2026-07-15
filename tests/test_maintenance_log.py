"""Maintenance-log → RCA corpus bridge tests (pure, no device).

Pins the mapping ladder (explicit cause → synonym → unambiguous keyword
inference → unmapped-with-reason), the no-guessing rule on ambiguity, signal
extraction, synonym validation, and the learn_cause_weights hand-off.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.maintenance_log import MAX_ROWS, corpus_from_maintenance_log


class TestCauseResolution:
    def test_explicit_taxonomy_cause_wins(self):
        out = corpus_from_maintenance_log([{"cause": "comms_loss"}], learn=False)
        assert out["corpus"] == [{"cause": "comms_loss", "signals": []}]
        assert out["mapped_via"] == {"explicit": 1}

    def test_builtin_synonyms_cover_english_and_chinese(self):
        rows = [{"category": "bearing failure"}, {"root_cause": "网络中断"}]
        out = corpus_from_maintenance_log(rows, learn=False)
        assert [r["cause"] for r in out["corpus"]] == ["mechanical_fault", "comms_loss"]
        assert out["mapped_via"] == {"synonym": 2}

    def test_caller_synonyms_extend_the_table(self):
        rows = [{"category": "spindle crash"}]
        out = corpus_from_maintenance_log(
            rows, synonyms={"Spindle Crash": "mechanical_fault"}, learn=False
        )
        assert out["corpus"][0]["cause"] == "mechanical_fault"

    def test_caller_synonym_with_unknown_cause_is_rejected(self):
        with pytest.raises(ValueError, match="not a taxonomy cause"):
            corpus_from_maintenance_log([], synonyms={"x": "gremlins"})

    def test_unambiguous_keyword_inference_from_free_text(self):
        rows = [{"description": "line stopped, PLC heartbeat timeout on the cell switch"}]
        out = corpus_from_maintenance_log(rows, learn=False)
        assert out["corpus"][0]["cause"] == "comms_loss"
        assert out["mapped_via"] == {"keyword inference (unambiguous)": 1}

    def test_ambiguous_text_is_never_guessed(self):
        rows = [{"description": "motor overload after sensor signal went bad"}]
        out = corpus_from_maintenance_log(rows, learn=False)
        assert out["corpus"] == []
        assert "ambiguous" in out["unmapped"][0]["reason"]
        # the reason names the competing causes so the operator can add a synonym
        assert "mechanical_fault" in out["unmapped"][0]["reason"]

    def test_row_without_cause_or_text_reports_why(self):
        out = corpus_from_maintenance_log([{"work_order": "WO-1"}], learn=False)
        assert out["n_mapped"] == 0
        assert "no cause column" in out["unmapped"][0]["reason"]


class TestSignals:
    def test_explicit_signals_are_filtered_to_taxonomy(self):
        rows = [{"cause": "comms_loss", "signals": ["comms_loss", "gremlins"]}]
        out = corpus_from_maintenance_log(rows, learn=False)
        assert out["corpus"][0]["signals"] == ["comms_loss"]

    def test_signals_inferred_from_symptom_text_can_be_many(self):
        rows = [{"cause": "mechanical_fault", "symptom": "drive overload + comms timeout alarm"}]
        out = corpus_from_maintenance_log(rows, learn=False)
        assert out["corpus"][0]["signals"] == ["comms_loss", "mechanical_fault"]

    def test_no_symptom_text_means_no_fabricated_signals(self):
        out = corpus_from_maintenance_log([{"cause": "changeover"}], learn=False)
        assert out["corpus"][0]["signals"] == []


class TestBoundaries:
    def test_rows_must_be_a_list(self):
        with pytest.raises(ValueError, match="list of work-order dicts"):
            corpus_from_maintenance_log({"cause": "comms_loss"})

    def test_non_dict_row_lands_in_unmapped(self):
        out = corpus_from_maintenance_log(["oops"], learn=False)
        assert out["unmapped"][0]["reason"] == "not a dict"

    def test_truncation_is_disclosed(self):
        rows = [{"cause": "comms_loss"}] * (MAX_ROWS + 1)
        out = corpus_from_maintenance_log(rows, learn=False)
        assert out["n_mapped"] == MAX_ROWS
        assert "truncated" in out


class TestLearnHandoff:
    def test_learn_true_includes_weights_with_thin_history_fallback(self):
        out = corpus_from_maintenance_log([{"cause": "comms_loss"}], learn=True)
        assert out["weights"]["cause_weights"] == {}
        assert "too thin" in out["weights"]["rationale"]

    def test_learn_false_omits_weights(self):
        out = corpus_from_maintenance_log([{"cause": "comms_loss"}], learn=False)
        assert "weights" not in out

    def test_end_to_end_learns_from_a_real_looking_export(self):
        rows = [
            {"category": "网络中断", "symptom": "PLC offline alarm"},
            {"category": "communication loss", "symptom": "heartbeat timeout"},
        ] * 5
        out = corpus_from_maintenance_log(rows, learn=True, min_samples=8)
        assert out["n_mapped"] == 10
        assert out["weights"]["n_incidents"] == 10
        assert out["weights"]["cause_weights"].get("comms_loss", 0) > 1.0
