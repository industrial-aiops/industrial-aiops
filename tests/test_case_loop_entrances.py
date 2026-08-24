"""The learning loop had no entrance and no exit.

`#173` built cases, capture modes and `to_corpus`; `#180` built `case list` /
`confirm` / `dismiss` and called itself "the entrance". Driving the loop against
a real collected history on 2026-08-24 showed two of its four links had no caller
outside their own module:

    open_case ──✗ no caller──> confirm ──> to_corpus ──✗ no caller──> learn_cause_weights

`iaiops case list` even printed "Cases are opened from detected stoppages" while
nothing opened one, so an empty list read as "you have had no stoppages" rather
than "nothing here ever creates a case". And `diag learn-weights` could only be
fed a hand-written JSON file — so the corpus the product spends years
accumulating could not reach the learner that exists to consume it.

The third test class covers a defect in the FIX: the first `case open` called
`open_case` for every rediscovered stoppage and then reported "1 already
answered" — having already replaced a human's label with a blank. Stoppage
detection is re-run by nature (a longer collection, a lower threshold), so that
would have quietly destroyed the most expensive data in the system on the second
run. The guard now lives in the store, where every caller gets it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from iaiops.core.knowledge.case_store import confirm_case, list_cases, open_case
from iaiops.core.knowledge.cases import to_corpus

pytestmark = pytest.mark.unit

SITE = "plant_a"
ONSET = "2026-08-24T01:12:18+00:00"


@pytest.fixture
def base(tmp_path):
    return tmp_path


def _audit(offset_s: float, tool: str = "modbus_write_register") -> dict:
    at = datetime.fromisoformat(ONSET) + timedelta(seconds=offset_s)
    return {
        "ts": at.isoformat(),
        "tool": tool,
        "status": "ok",
        "risk_level": "high",
        "user": "zhang",
        "params": "{}",
        "approved_by": "wei",
    }


class TestAStoppageCanBecomeACase:
    def test_opening_stores_a_case_that_list_finds(self, base):
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        assert [c.incident_id for c in list_cases(SITE, base_dir=base)] == ["line1-20260824T011218"]

    def test_it_starts_with_no_label(self, base):
        """What the actions imply about the cause is for a person to say."""
        case = open_case(SITE, "line1", ONSET, audit_rows=[_audit(60)], base_dir=base)
        assert case.label == ""
        assert list_cases(SITE, pending_only=True, base_dir=base)

    def test_it_carries_what_someone_did_afterwards(self, base):
        """Zero extra typing: the actions were already recorded."""
        case = open_case(SITE, "line1", ONSET, audit_rows=[_audit(240)], base_dir=base)
        assert [a["tool"] for a in case.fix_actions] == ["modbus_write_register"]

    def test_an_action_before_the_stoppage_is_not_a_response_to_it(self, base):
        case = open_case(SITE, "line1", ONSET, audit_rows=[_audit(-600)], base_dir=base)
        assert case.fix_actions == ()

    def test_the_same_stoppage_reopens_as_the_same_case(self, base):
        """Detection is re-run by nature; a duplicate per run would be useless."""
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        assert len(list_cases(SITE, base_dir=base)) == 1


class TestAnAnsweredCaseIsNeverOverwritten:
    """The defect in the first version of the fix — see the module docstring."""

    def test_reopening_keeps_the_label(self, base):
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        confirm_case(
            SITE, "line1-20260824T011218", cause="material_starvation", by="wei", base_dir=base
        )
        open_case(SITE, "line1", ONSET, audit_rows=[_audit(30)], base_dir=base)
        assert list_cases(SITE, base_dir=base)[0].label == "material_starvation"

    def test_reopening_returns_the_answered_case_rather_than_a_blank_one(self, base):
        """The caller must not be told it opened something new — the counter that
        said '1 already answered' was true while the answer was already gone."""
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        confirm_case(SITE, "line1-20260824T011218", cause="comms_loss", by="wei", base_dir=base)
        again = open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        assert again.label == "comms_loss"

    def test_reopening_keeps_a_dismissal(self, base):
        """A dismissal is a label too — "not an incident" is the cheapest and
        usually most plentiful signal in the loop. Re-detecting the stoppage must
        not put it back on the pile the operator already cleared."""
        from iaiops.core.knowledge.case_store import dismiss_case

        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        dismiss_case(SITE, "line1-20260824T011218", by="wei", base_dir=base)
        open_case(SITE, "line1", ONSET, audit_rows=[_audit(30)], base_dir=base)
        assert list_cases(SITE, pending_only=True, base_dir=base) == []

    def test_a_dismissed_case_is_answered(self, base):
        from iaiops.core.knowledge.case_store import dismiss_case

        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        dismiss_case(SITE, "line1-20260824T011218", by="wei", base_dir=base)
        assert list_cases(SITE, base_dir=base)[0].answered is True

    def test_a_still_pending_case_is_refreshed(self, base):
        """Unanswered, a re-run SHOULD pick up actions recorded since — the guard
        is about protecting answers, not about freezing the case."""
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        again = open_case(SITE, "line1", ONSET, audit_rows=[_audit(120)], base_dir=base)
        assert len(again.fix_actions) == 1

    def test_a_pending_case_with_a_note_is_still_pending(self, base):
        """Every case carries an explanatory note. The first guard matched on
        that, so it froze pending cases while claiming to protect answers."""
        case = open_case(SITE, "line1", ONSET, audit_rows=[_audit(60)], base_dir=base)
        assert case.note and case.answered is False


class TestConfirmedCasesReachTheLearner:
    def test_a_confirmed_case_becomes_corpus(self, base):
        open_case(SITE, "line1", ONSET, ranked=("comms_loss",), audit_rows=[], base_dir=base)
        confirm_case(SITE, "line1-20260824T011218", cause="comms_loss", by="wei", base_dir=base)
        corpus = to_corpus(list_cases(SITE, base_dir=base))
        assert corpus == [{"cause": "comms_loss", "signals": ["comms_loss"]}]

    def test_an_unanswered_case_is_not_evidence(self, base):
        open_case(SITE, "line1", ONSET, audit_rows=[], base_dir=base)
        assert to_corpus(list_cases(SITE, base_dir=base)) == []

    def test_anchored_labels_can_be_excluded_without_deleting_them(self, base):
        """A site checks whether its weights survive without the labels its own
        tool shaped — the anchoring control is the point of the loop being honest."""
        open_case(SITE, "line1", ONSET, ranked=("comms_loss",), audit_rows=[], base_dir=base)
        confirm_case(SITE, "line1-20260824T011218", cause="comms_loss", by="wei", base_dir=base)
        assert to_corpus(list_cases(SITE, base_dir=base), include_anchored=False) == []
        assert to_corpus(list_cases(SITE, base_dir=base)) != []
