"""Opening a case, and confirming it in one choice.

#173 built the loop — cases, capture modes, the corpus that feeds
`learn_cause_weights` — but nothing could CREATE a case, so the loop had no
entry. This closes it: a stoppage becomes a case, the case waits for a person,
and one choice turns it into a label.

Two rules that are easy to lose and expensive to lose:

**The capture mode is DERIVED, never declared by the person answering.** Whether
an answer was anchored depends on what we had already suggested, not on what the
answerer says about themselves. Letting anyone mark their own answer "stated"
would defeat the anchoring guard entirely — and defeat it silently, since the
agreement rate would still look healthy.

**The cause comes from the taxonomy, not from a text box.** The whole reason
`maintenance_log.py` needs painful synonym mapping is that CMMS free text says
"bearing failure", "网络中断" and "Fixed it" for things a model cannot use. A
label captured at diagnosis time should enter in the vocabulary the learner
already speaks.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.rca_weights import LEARNABLE_CAUSES
from iaiops.core.knowledge.case_store import (
    confirm_case,
    dismiss_case,
    list_cases,
    open_case,
)
from iaiops.core.knowledge.cases import CONFIRMED, INFERRED, OVERRIDE

pytestmark = pytest.mark.unit

WHEN = "2026-08-01T03:00:00+00:00"
AUDIT = [
    {
        "ts": "2026-08-01T03:04:00+00:00",
        "tool": "modbus_write_register",
        "params": '{"endpoint": "line1"}',
        "status": "ok",
        "risk_level": "high",
        "user": "zhang",
    }
]


def opened(tmp_path, ranked=("mechanical_fault", "comms_loss"), audit=None):
    return open_case(
        site="plant-a",
        endpoint="line1",
        when=WHEN,
        ranked=ranked,
        audit_rows=audit if audit is not None else AUDIT,
        base_dir=tmp_path,
    )


class TestOpeningACase:
    def test_a_stoppage_becomes_a_case_awaiting_a_cause(self, tmp_path):
        case = opened(tmp_path)
        assert case.label == ""
        assert case.counts_as_evidence is False

    def test_it_captures_what_someone_did_from_the_audit_trail(self, tmp_path):
        """Zero extra typing — the action already happened and was recorded."""
        case = opened(tmp_path)
        assert case.fix_actions and case.fix_actions[0]["tool"] == "modbus_write_register"

    def test_it_starts_as_inferred_when_there_were_actions(self, tmp_path):
        assert opened(tmp_path).capture == INFERRED

    def test_a_case_with_no_actions_has_no_capture_mode_yet(self, tmp_path):
        assert opened(tmp_path, audit=[]).capture == ""

    def test_it_keeps_what_we_ranked_so_anchoring_can_be_judged_later(self, tmp_path):
        assert opened(tmp_path).ranked == ("mechanical_fault", "comms_loss")

    def test_it_persists_and_can_be_listed(self, tmp_path):
        opened(tmp_path)
        assert len(list_cases("plant-a", base_dir=tmp_path)) == 1

    def test_two_cases_get_distinct_ids(self, tmp_path):
        a = opened(tmp_path)
        b = open_case(
            site="plant-a",
            endpoint="line1",
            when="2026-08-01T09:00:00+00:00",
            ranked=("comms_loss",),
            audit_rows=[],
            base_dir=tmp_path,
        )
        assert a.incident_id != b.incident_id


class TestTheCaptureModeIsDerived:
    def test_picking_our_top_hypothesis_is_anchored(self, tmp_path):
        case = opened(tmp_path)
        done = confirm_case(
            "plant-a", case.incident_id, cause="mechanical_fault", by="wei", base_dir=tmp_path
        )
        assert done.capture == CONFIRMED
        assert done.anchored is True

    def test_naming_a_cause_we_did_not_rank_is_an_override(self, tmp_path):
        """They disagreed with everything we offered, so nothing anchored it."""
        case = opened(tmp_path)
        done = confirm_case(
            "plant-a", case.incident_id, cause="changeover", by="wei", base_dir=tmp_path
        )
        assert done.capture == OVERRIDE
        assert done.anchored is False

    def test_a_lower_ranked_hypothesis_still_counts_as_anchored(self, tmp_path):
        """It came from our list, even if it was not our first choice."""
        case = opened(tmp_path)
        done = confirm_case(
            "plant-a", case.incident_id, cause="comms_loss", by="wei", base_dir=tmp_path
        )
        assert done.capture == CONFIRMED

    def test_the_answerer_cannot_choose_their_own_capture_mode(self, tmp_path):
        """The guard that makes the anchoring measurement mean anything."""
        import inspect

        assert "capture" not in inspect.signature(confirm_case).parameters


class TestTheCauseComesFromTheTaxonomy:
    def test_a_cause_outside_the_vocabulary_is_refused(self, tmp_path):
        case = opened(tmp_path)
        with pytest.raises(ValueError, match="(?i)cause"):
            confirm_case(
                "plant-a", case.incident_id, cause="bearing went bang", by="wei", base_dir=tmp_path
            )

    def test_the_refusal_lists_every_allowed_cause(self, tmp_path):
        case = opened(tmp_path)
        with pytest.raises(ValueError) as excinfo:
            confirm_case("plant-a", case.incident_id, cause="nope", by="wei", base_dir=tmp_path)
        missing = [c for c in LEARNABLE_CAUSES if c not in str(excinfo.value)]
        assert not missing

    def test_every_taxonomy_cause_is_accepted(self, tmp_path):
        for n, cause in enumerate(sorted(LEARNABLE_CAUSES)):
            case = open_case(
                site="plant-a",
                endpoint="line1",
                when=f"2026-08-01T0{n}:00:00+00:00",
                ranked=(),
                audit_rows=[],
                base_dir=tmp_path,
            )
            done = confirm_case(
                "plant-a", case.incident_id, cause=cause, by="wei", base_dir=tmp_path
            )
            assert done.label == cause


class TestWhoAnsweredIsRecorded:
    def test_confirming_without_a_name_is_refused(self, tmp_path):
        case = opened(tmp_path)
        with pytest.raises(ValueError, match="(?i)who|by"):
            confirm_case("plant-a", case.incident_id, cause="comms_loss", by="", base_dir=tmp_path)

    def test_the_confirmation_is_attributable(self, tmp_path):
        case = opened(tmp_path)
        confirm_case(
            "plant-a", case.incident_id, cause="comms_loss", by="engineer:li", base_dir=tmp_path
        )
        stored = list_cases("plant-a", base_dir=tmp_path)[0]
        assert "engineer:li" in stored.note


class TestDismissalIsAFreeNegativeLabel:
    def test_dismissing_records_that_it_was_not_an_incident(self, tmp_path):
        case = opened(tmp_path)
        done = dismiss_case("plant-a", case.incident_id, by="wei", base_dir=tmp_path)
        assert done.label == ""
        assert "dismissed" in done.note.lower()

    def test_a_dismissed_case_does_not_train_the_weights(self, tmp_path):
        case = opened(tmp_path)
        dismiss_case("plant-a", case.incident_id, by="wei", base_dir=tmp_path)
        stored = list_cases("plant-a", base_dir=tmp_path)[0]
        assert stored.counts_as_evidence is False

    def test_a_dismissed_case_is_no_longer_pending(self, tmp_path):
        case = opened(tmp_path)
        dismiss_case("plant-a", case.incident_id, by="wei", base_dir=tmp_path)
        assert list_cases("plant-a", pending_only=True, base_dir=tmp_path) == []


class TestListing:
    def test_pending_only_hides_answered_cases(self, tmp_path):
        a = opened(tmp_path)
        open_case(
            site="plant-a",
            endpoint="line1",
            when="2026-08-02T03:00:00+00:00",
            ranked=(),
            audit_rows=[],
            base_dir=tmp_path,
        )
        confirm_case("plant-a", a.incident_id, cause="comms_loss", by="wei", base_dir=tmp_path)
        assert len(list_cases("plant-a", pending_only=True, base_dir=tmp_path)) == 1

    def test_a_site_with_no_cases_lists_nothing_rather_than_failing(self, tmp_path):
        assert list_cases("empty-site", base_dir=tmp_path) == []

    def test_confirming_an_unknown_case_is_reported_clearly(self, tmp_path):
        with pytest.raises(KeyError, match="(?i)nope"):
            confirm_case("plant-a", "nope", cause="comms_loss", by="wei", base_dir=tmp_path)
