"""Cases — what the tool said, what a person said, and which of those may teach it.

This closes the loop `rca_weights.learn_cause_weights` has been waiting for. The
learner existed; its corpus could only be IMPORTED — from a CMMS export or a
hand-written JSON file — so the tool could be used for two years and stay exactly
as clever as on day one.

Two hazards shape the design, and both are about the tool fooling itself:

**Anchoring.** If a person picks a cause from OUR ranked list, that is a usable
label but not an independent one. Feed enough anchored labels back into the
weights and the system converges on whatever it already believed, growing more
confident and less correct. So capture mode is recorded per case, agreement is
reported per mode, and an unusually HIGH agreement rate is treated as a warning
rather than a triumph — on a real plant, a tool that agrees with the expert 95%
of the time is more likely to be leading them than to be right.

**Inference from the audit trail.** `~/.iaiops/audit.db` reliably records what
someone DID after a stoppage. What that action implies about the CAUSE is a
guess. So the audit trail yields `suggested` facts needing confirmation, never
labels — which is exactly what the provenance model is for.
"""

from __future__ import annotations

import pytest

from iaiops.core.knowledge.cases import (
    ANCHORED_MODES,
    CONFIRMED,
    HIGH_AGREEMENT_WARN,
    INFERRED,
    OVERRIDE,
    STATED,
    Case,
    agreement_report,
    case_from_audit,
    to_corpus,
)

pytestmark = pytest.mark.unit


def case(cause="bearing", capture=STATED, top="bearing", **kw):
    return Case(
        incident_id=kw.pop("incident_id", "i1"),
        when="2026-08-01T03:00:00+00:00",
        ranked=kw.pop("ranked", (top, "comms_loss")),
        label=cause,
        capture=capture,
        **kw,
    )


class TestOnlyEvidenceTeaches:
    def test_a_case_with_no_label_teaches_nothing(self):
        assert Case(incident_id="i", when="t", ranked=("a",)).counts_as_evidence is False

    def test_a_stated_cause_is_evidence(self):
        assert case(capture=STATED).counts_as_evidence is True

    def test_an_override_is_evidence(self):
        """They disagreed with us, so nothing we said anchored the answer."""
        assert case(cause="material", capture=OVERRIDE, top="bearing").counts_as_evidence is True

    def test_a_pick_from_our_list_is_evidence_but_anchored(self):
        picked = case(capture=CONFIRMED)
        assert picked.counts_as_evidence is True
        assert picked.anchored is True

    def test_stated_and_override_are_not_anchored(self):
        assert case(capture=STATED).anchored is False
        assert case(capture=OVERRIDE).anchored is False
        assert set(ANCHORED_MODES) == {CONFIRMED}

    def test_an_inference_from_the_audit_trail_is_not_a_label(self):
        """The audit trail records what someone DID. What that implies about the
        cause is a guess, and a guess must not train the weights."""
        assert case(capture=INFERRED).counts_as_evidence is False

    def test_an_unknown_capture_mode_is_refused(self):
        with pytest.raises(ValueError, match="(?i)capture"):
            case(capture="probably")

    def test_a_label_requires_a_capture_mode(self):
        with pytest.raises(ValueError, match="(?i)capture"):
            Case(incident_id="i", when="t", ranked=("a",), label="bearing")


class TestTheCorpusThatClosesTheLoop:
    def test_it_produces_what_the_learner_consumes(self):
        corpus = to_corpus([case(cause="bearing", ranked=("bearing", "comms_loss"))])
        assert corpus == [{"cause": "bearing", "signals": ["bearing", "comms_loss"]}]

    def test_non_evidence_cases_are_excluded(self):
        corpus = to_corpus([case(capture=INFERRED), case(capture=STATED)])
        assert len(corpus) == 1

    def test_the_corpus_actually_feeds_the_learner(self):
        """The integration that proves the loop is closed rather than merely
        shaped like it."""
        from iaiops.core.brain.rca_weights import learn_cause_weights

        cases = [
            case(incident_id=f"i{n}", cause="comms_loss", ranked=("comms_loss",)) for n in range(30)
        ]
        result = learn_cause_weights(to_corpus(cases))
        assert result["n_incidents"] == 30

    def test_anchored_cases_can_be_excluded_from_training(self):
        """A site that wants to learn only from independent labels must be able
        to, without deleting its own history."""
        cases = [case(capture=CONFIRMED), case(capture=STATED)]
        assert len(to_corpus(cases, include_anchored=False)) == 1


class TestAgreementIsWatchedNotCelebrated:
    def _cases(self, agree: int, disagree: int):
        out = [
            case(incident_id=f"a{n}", cause="bearing", capture=CONFIRMED, top="bearing")
            for n in range(agree)
        ]
        out += [
            case(incident_id=f"d{n}", cause="material", capture=OVERRIDE, top="bearing")
            for n in range(disagree)
        ]
        return out

    def test_it_reports_how_often_the_human_agreed(self):
        report = agreement_report(self._cases(agree=6, disagree=4))
        assert report["agreement_pct"] == pytest.approx(60.0)

    def test_it_splits_agreement_by_capture_mode(self):
        """Aggregate agreement hides the thing worth seeing: whether the
        agreement came from independent statements or from picking our list."""
        report = agreement_report(self._cases(agree=6, disagree=4))
        assert report["by_capture"][CONFIRMED] == 6
        assert report["by_capture"][OVERRIDE] == 4

    def test_suspiciously_high_agreement_is_flagged(self):
        """A tool that agrees with the expert 95% of the time on a real plant is
        more likely to be LEADING them than to be right."""
        report = agreement_report(self._cases(agree=39, disagree=1))
        assert report["warning"]
        assert "anchor" in report["warning"].lower()

    def test_the_flag_needs_enough_cases_to_mean_anything(self):
        """Three out of three is not evidence of anchoring, it is three cases."""
        assert not agreement_report(self._cases(agree=3, disagree=0))["warning"]

    def test_a_healthy_mix_is_not_flagged(self):
        assert not agreement_report(self._cases(agree=24, disagree=16))["warning"]

    def test_the_threshold_is_stated_not_implied(self):
        assert agreement_report(self._cases(agree=6, disagree=4))["warn_above_pct"] == (
            HIGH_AGREEMENT_WARN
        )

    def test_anchored_share_is_reported_separately(self):
        """The number that actually predicts drift."""
        report = agreement_report(self._cases(agree=6, disagree=4))
        assert report["anchored_pct"] == pytest.approx(60.0)


class TestFromTheAuditTrail:
    AUDIT = [
        {
            "ts": "2026-08-01T03:04:00+00:00",
            "tool": "modbus_write_register",
            "params": '{"endpoint": "line1", "address": 40010}',
            "status": "ok",
            "risk_level": "high",
            "user": "zhang",
        },
        {
            "ts": "2026-08-01T03:02:00+00:00",
            "tool": "modbus_read_holding",
            "status": "ok",
            "risk_level": "low",
            "user": "zhang",
        },
    ]

    def test_it_captures_what_a_person_actually_did(self):
        """Zero extra typing — this already happened and was already recorded."""
        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", self.AUDIT)
        assert result.fix_actions
        assert result.fix_actions[0]["tool"] == "modbus_write_register"

    def test_reads_are_not_fixes(self):
        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", self.AUDIT)
        assert all(a["tool"] != "modbus_read_holding" for a in result.fix_actions)

    def test_it_yields_no_label(self):
        """The action is a fact; what it says about the cause is not."""
        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", self.AUDIT)
        assert result.label == ""
        assert result.counts_as_evidence is False

    def test_actions_before_the_incident_are_excluded(self):
        earlier = [{**self.AUDIT[0], "ts": "2026-08-01T02:00:00+00:00"}]
        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", earlier)
        assert result.fix_actions == ()

    def test_failed_actions_are_excluded(self):
        failed = [{**self.AUDIT[0], "status": "error"}]
        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", failed)
        assert result.fix_actions == ()

    def test_it_becomes_a_suggestion_for_a_human_to_confirm(self):
        """Composes with the provenance model: audit → suggested → confirmed."""
        from iaiops.core.knowledge.model import SUGGESTED

        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", self.AUDIT)
        assert result.as_fact().source == SUGGESTED
        assert result.as_fact().usable is False

    def test_confirming_that_suggestion_records_who(self):
        result = case_from_audit("i1", "2026-08-01T03:00:00+00:00", self.AUDIT)
        confirmed = result.as_fact().confirmed_by("engineer:li")
        assert confirmed.usable is True and confirmed.confirmed_by_whom == "engineer:li"
