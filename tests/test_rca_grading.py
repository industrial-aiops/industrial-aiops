"""A verdict that is also an investigation plan — and a grade nothing can fake.

Three gaps, recorded as HLD §10.3④ / D28-D30 after studying how a mature IT-side
log-analysis platform organises an investigation. What transferred is the part
that needs no model at all: an evidence ledger, four conclusion grades, and
exclusion by time order. What did NOT transfer is that platform's own destination
— a stateful LLM agent — which would contradict §1's zero-model guarantee.

**A confidence is not a plan.** A ranked list says what we think, not what to go
and get. Each hypothesis now carries its counter-evidence, its GAPS, and one next
step. In a plant the gap is usually a field action — somebody with an instrument
— not another pass over registers already collected.

**"Ruled out" is stronger than "scored low."** `_proximity_scale` already knew a
signal came after the onset and dropped it to a quarter weight, then discarded the
reason. A quarter weight says "unlikely"; naming the timing says "stop looking
down this branch", and only the second saves anybody an afternoon.

**A high confidence is the ranking agreeing with itself.** It is computed from the
same evidence that produced the ranking, so it cannot verify it. `confirmed` is
reachable only from outside: a measurement, a reproduction, or a person.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.rca import (
    CANDIDATE,
    CONFIRMED,
    EXCLUDED,
    PROBABLE,
    downtime_rca,
)

pytestmark = pytest.mark.unit

WINDOW = {"start": "2026-08-24T10:00:00Z", "end": "2026-08-24T10:20:00Z", "asset": "Line 1"}

BEFORE = "2026-08-24T09:58:00Z"  # two minutes before the stoppage
AFTER = "2026-08-24T10:07:00Z"  # seven minutes after it


def alarm(message: str, at: str | None, source: str = "PUMP_01") -> dict:
    row = {"source": source, "message": message}
    if at is not None:
        row["timestamp"] = at
    return row


def verdict(**kwargs) -> dict:
    return downtime_rca(WINDOW, **kwargs)


def hypothesis(out: dict, cause: str) -> dict:
    return next(h for h in out["hypotheses"] if h["cause"] == cause)


class TestACauseCannotFollowItsEffect:
    def test_a_cause_supported_only_after_the_onset_is_excluded(self):
        """The operator reacting to a stoppage is the classic false root cause."""
        out = verdict(alarms=[alarm("manual changeover started", AFTER, "OP_STATION")])
        assert hypothesis(out, "changeover")["grade"] == EXCLUDED

    def test_the_exclusion_states_its_reason(self):
        """A grade without a reason is just a smaller number."""
        out = verdict(alarms=[alarm("manual changeover started", AFTER, "OP_STATION")])
        counter = hypothesis(out, "changeover")["counter_evidence"]
        assert counter and "AFTER the onset" in counter[0]["reason"]
        assert "420s" in counter[0]["reason"], "the reason should name how long after"

    def test_a_cause_before_the_onset_is_not_excluded(self):
        """The complement: an implementation that excluded everything would pass
        the tests above."""
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        assert hypothesis(out, "comms_loss")["grade"] != EXCLUDED

    def test_mixed_timing_does_not_exclude_even_when_most_are_after(self):
        """ONE signal before the onset and the cause is live again — two-against-one
        is not enough. Exclusion is the strongest thing this module emits and may
        not rest on a majority: the single pre-onset signal might be the real one,
        and the two later ones the plant reacting to it.

        Deliberately lopsided. A one-and-one fixture cannot tell an all-rule from
        a majority-rule apart, which is how the first version of this test let a
        majority-rule mutation through."""
        out = verdict(
            alarms=[
                alarm("communication timeout on link", BEFORE),
                alarm("communication timeout on link", AFTER, "PUMP_02"),
                alarm("communication timeout on link", AFTER, "PUMP_03"),
            ]
        )
        assert hypothesis(out, "comms_loss")["grade"] != EXCLUDED

    def test_the_lone_pre_onset_signal_is_not_listed_as_counter_evidence(self):
        """The complement: only the later ones argue against the timing."""
        out = verdict(
            alarms=[
                alarm("communication timeout on link", BEFORE),
                alarm("communication timeout on link", AFTER, "PUMP_02"),
            ]
        )
        counter = hypothesis(out, "comms_loss")["counter_evidence"]
        assert [c["ref"] for c in counter] == ["PUMP_02"]

    def test_untimed_evidence_never_excludes(self):
        """An alarm with no timestamp says nothing about order, and a gap in the
        data must never be read as an argument."""
        out = verdict(alarms=[alarm("manual changeover started", None, "OP_STATION")])
        assert hypothesis(out, "changeover")["grade"] != EXCLUDED

    def test_an_excluded_cause_is_never_the_primary_even_when_it_outscores(self):
        """The behavioural payoff, and it has to be set up so the exclusion is what
        decides. A single post-onset alarm scores 0.125 — below the reporting floor
        — so `primary` is None whether or not the exclusion works, and a test built
        that way passes for the wrong reason. (It did; a mutation removing the
        filter survived it.)

        So: a dozen post-onset signals for one cause, which out-scores a single
        legitimate pre-onset signal. Without the exclusion the ruled-out cause wins
        the ranking and is handed over as the answer."""
        out = verdict(
            alarms=[
                *[alarm("manual changeover started", AFTER, f"OP_{i}") for i in range(12)],
                alarm("communication timeout on link", BEFORE),
            ]
        )
        changeover = hypothesis(out, "changeover")
        comms = hypothesis(out, "comms_loss")
        assert changeover["grade"] == EXCLUDED
        assert changeover["confidence"] > comms["confidence"], (
            "the setup must have the excluded cause out-scoring the real one, "
            "or the test does not exercise the exclusion"
        )
        assert out["primary_cause"]["cause"] == "comms_loss"

    def test_the_excluded_causes_are_reported_as_their_own_block(self):
        """ "We ruled this out" is a finding. Dropping it silently just looks like
        the tool never considered it."""
        out = verdict(alarms=[alarm("manual changeover started", AFTER, "OP_STATION")])
        assert [e["cause"] for e in out["excluded"]] == ["changeover"]

    def test_an_exclusion_names_what_would_overturn_it(self):
        """It rests entirely on timestamps, and clock drift between a device, a
        gateway and the collector is ordinary."""
        out = verdict(alarms=[alarm("manual changeover started", AFTER, "OP_STATION")])
        gaps = " ".join(hypothesis(out, "changeover")["gaps"])
        assert "clock" in gaps.lower()


class TestConfirmedCannotBeReachedFromTheInside:
    """D29. This is the load-bearing refusal of the whole grading scheme."""

    def test_evidence_alone_never_reaches_confirmed(self):
        out = verdict(
            alarms=[
                alarm("communication timeout on link", BEFORE),
                alarm("link down", BEFORE, "SWITCH_01"),
                alarm("communication timeout on link", BEFORE, "PUMP_03"),
            ]
        )
        assert all(h["grade"] != CONFIRMED for h in out["hypotheses"])

    def test_even_the_highest_confidence_is_only_probable(self):
        """A confidence computed from the evidence that produced the ranking means
        the ranking agrees with itself."""
        out = verdict(
            alarms=[alarm("communication timeout on link", BEFORE, f"PUMP_{i}") for i in range(8)]
        )
        top = out["hypotheses"][0]
        assert top["confidence"] >= 0.7
        assert top["grade"] == PROBABLE

    def test_a_measurement_promotes_it(self):
        out = verdict(
            alarms=[alarm("communication timeout on link", BEFORE)],
            confirmation={"cause": "comms_loss", "basis": "measurement", "by": "wei"},
        )
        assert hypothesis(out, "comms_loss")["grade"] == CONFIRMED

    def test_a_confirmed_cause_becomes_the_verdict_whatever_it_scored(self):
        """It is the only thing that outranks the score, because it is the only
        thing that came from outside it."""
        out = verdict(
            alarms=[alarm("communication timeout on link", BEFORE)],
            confirmation={"cause": "comms_loss", "basis": "human", "by": "wei"},
        )
        assert out["verdict"] == "root_cause_identified"
        assert out["primary_cause"]["cause"] == "comms_loss"

    def test_only_the_confirmed_cause_is_promoted(self):
        """The complement: promoting everything would pass the test above."""
        out = verdict(
            alarms=[
                alarm("communication timeout on link", BEFORE),
                alarm("bearing vibration high", BEFORE, "MOTOR_01"),
            ],
            confirmation={"cause": "comms_loss", "basis": "human", "by": "wei"},
        )
        others = [h for h in out["hypotheses"] if h["cause"] != "comms_loss"]
        assert others and all(h["grade"] != CONFIRMED for h in others)

    def test_the_confirmation_is_recorded_with_its_basis(self):
        """Who said so, and on what — a confirmation with no provenance is just a
        stronger word."""
        out = verdict(
            alarms=[alarm("communication timeout on link", BEFORE)],
            confirmation={"cause": "comms_loss", "basis": "reproduction", "by": "zhang"},
        )
        assert out["confirmation"]["basis"] == "reproduction"
        assert out["confirmation"]["by"] == "zhang"

    @pytest.mark.parametrize(
        "bad",
        [
            {"cause": "comms_loss", "basis": "vibes"},
            {"cause": "not_a_cause", "basis": "human"},
            {"cause": "comms_loss"},
            "just a string",
            ["comms_loss"],
        ],
    )
    def test_a_malformed_confirmation_is_refused_not_ignored(self, bad):
        """Silently ignoring it would leave the operator believing a verdict had
        been verified when it had not — the exact failure this grade prevents."""
        with pytest.raises(ValueError):
            verdict(alarms=[alarm("communication timeout on link", BEFORE)], confirmation=bad)

    def test_no_confirmation_is_not_an_error(self):
        """It is the ordinary case, not a malformed one."""
        assert verdict(alarms=[alarm("communication timeout on link", BEFORE)], confirmation=None)


class TestTheConclusionIsAlsoAPlan:
    def test_every_unconfirmed_hypothesis_says_what_is_missing(self):
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        for h in out["hypotheses"]:
            if h["grade"] != CONFIRMED:
                assert h["gaps"], f"{h['cause']} offers no gap"

    def test_the_gap_is_a_field_action_not_another_query(self):
        """The difference between this and an IT investigation: there, more
        evidence is usually already on disk."""
        out = verdict(alarms=[alarm("bearing vibration high", BEFORE, "MOTOR_01")])
        gaps = " ".join(hypothesis(out, "mechanical_fault")["gaps"]).lower()
        assert "vibration" in gaps or "maintenance record" in gaps

    def test_every_unconfirmed_hypothesis_offers_one_next_step(self):
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        step = hypothesis(out, "comms_loss")["next_step"]
        assert "case confirm" in step, "the next step should reach the loop that already exists"

    def test_a_confirmed_hypothesis_has_no_gaps_left(self):
        """The complement: an implementation that always listed gaps would pass
        the tests above."""
        out = verdict(
            alarms=[alarm("communication timeout on link", BEFORE)],
            confirmation={"cause": "comms_loss", "basis": "measurement", "by": "wei"},
        )
        h = hypothesis(out, "comms_loss")
        assert h["gaps"] == [] and h["next_step"] == ""

    def test_being_unconfirmed_is_itself_named_as_the_gap(self):
        """Not just 'we lack a vibration reading' but 'nobody has checked this
        against reality' — the second is true of every ranking, always."""
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        assert any("confirmed" in g for g in hypothesis(out, "comms_loss")["gaps"])

    def test_counter_evidence_is_empty_when_nothing_argues_against(self):
        """The complement to the exclusion tests: an implementation that listed
        every item as counter-evidence would pass those."""
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        assert hypothesis(out, "comms_loss")["counter_evidence"] == []


class TestTheOldContractSurvives:
    def test_the_existing_keys_are_all_still_there(self):
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        for key in ("verdict", "hypotheses", "evidence_summary", "anti_hallucination"):
            assert key in out
        h = out["hypotheses"][0]
        for key in ("cause", "confidence", "confidence_band", "evidence", "recommended_action"):
            assert key in h

    def test_grades_do_not_disturb_the_ranking(self):
        """Ordering is still by confidence; the grade describes a hypothesis, it
        does not reorder them."""
        out = verdict(
            alarms=[
                alarm("communication timeout on link", BEFORE),
                alarm("communication timeout on link", BEFORE, "PUMP_02"),
                alarm("bearing vibration high", BEFORE, "MOTOR_01"),
            ]
        )
        confidences = [h["confidence"] for h in out["hypotheses"]]
        assert confidences == sorted(confidences, reverse=True)

    def test_a_verdict_with_no_evidence_is_still_insufficient(self):
        assert verdict()["verdict"] == "insufficient_evidence"

    def test_every_hypothesis_carries_a_grade(self):
        out = verdict(alarms=[alarm("communication timeout on link", BEFORE)])
        assert all(
            h["grade"] in (CANDIDATE, PROBABLE, CONFIRMED, EXCLUDED) for h in out["hypotheses"]
        )


class TestTheConfirmationHasAnEntrance:
    """A capability with no caller does not exist (the #191 lesson). The loop that
    captures a human's cause already existed; the verdict could not see it."""

    def _case(self, tmp_path, label: str = "comms_loss"):
        from iaiops.core.knowledge.case_store import confirm_case, open_case

        open_case("default", "line1", "2026-08-24T10:00:00+00:00", audit_rows=[], base_dir=tmp_path)
        if label:
            confirm_case(
                "default", "line1-20260824T100000", cause=label, by="wei", base_dir=tmp_path
            )
        return "line1-20260824T100000"

    def test_a_confirmed_case_reaches_the_verdict(self, tmp_path, monkeypatch):
        from iaiops.cli.diagnostics import _confirmation_from

        incident = self._case(tmp_path)
        monkeypatch.setattr(
            "iaiops.core.knowledge.case_store.load",
            lambda site, base_dir=None: __import__(
                "iaiops.core.knowledge.store", fromlist=["load"]
            ).load(site, base_dir=tmp_path),
        )
        got = _confirmation_from(incident, "", "", "wei", "default")
        assert got == {"cause": "comms_loss", "basis": "human", "by": "wei"}

    def test_an_unanswered_case_is_refused_with_the_command_to_answer_it(
        self, tmp_path, monkeypatch
    ):
        from iaiops.cli.diagnostics import _confirmation_from

        incident = self._case(tmp_path, label="")
        monkeypatch.setattr(
            "iaiops.core.knowledge.case_store.load",
            lambda site, base_dir=None: __import__(
                "iaiops.core.knowledge.store", fromlist=["load"]
            ).load(site, base_dir=tmp_path),
        )
        with pytest.raises(ValueError) as excinfo:
            _confirmation_from(incident, "", "", "", "default")
        assert "case confirm" in str(excinfo.value)

    def test_a_missing_case_is_a_lookup_error_not_a_silent_none(self, tmp_path, monkeypatch):
        """Silently returning None would run the RCA ungraded and look like it
        worked — the operator would read an unverified verdict as verified."""
        from iaiops.cli.diagnostics import _confirmation_from

        monkeypatch.setattr(
            "iaiops.core.knowledge.case_store.load",
            lambda site, base_dir=None: __import__(
                "iaiops.core.knowledge.store", fromlist=["load"]
            ).load(site, base_dir=tmp_path),
        )
        with pytest.raises(LookupError):
            _confirmation_from("nope", "", "", "", "default")

    def test_the_two_routes_may_not_be_mixed(self):
        from iaiops.cli.diagnostics import _confirmation_from

        with pytest.raises(ValueError) as excinfo:
            _confirmation_from("some-case", "comms_loss", "measurement", "", "default")
        assert "not both" in str(excinfo.value)

    def test_a_cause_without_a_basis_is_refused(self):
        """Which of the three bases applies IS the claim. A default would let
        'somebody eyeballed it' be recorded as a measurement."""
        from iaiops.cli.diagnostics import _confirmation_from

        with pytest.raises(ValueError):
            _confirmation_from("", "comms_loss", "", "wei", "default")

    def test_no_flags_means_no_confirmation(self):
        """The ordinary case. Most verdicts are unconfirmed and must stay so."""
        from iaiops.cli.diagnostics import _confirmation_from

        assert _confirmation_from("", "", "", "", "default") is None


class TestAPersonOutranksAHeuristic:
    """Found by audit 2026-08-25. `_grade` tested `ruled_out` BEFORE `confirmed`,
    so a cause an engineer had confirmed was graded `excluded` by a timestamp
    comparison and handed back a lecture about clock skew — D29 inverted in the
    one place D29 is about."""

    def test_a_confirmed_cause_survives_the_timing_objection(self):
        out = verdict(
            alarms=[alarm("manual changeover started", AFTER, "OP_STATION")],
            confirmation={"cause": "changeover", "basis": "measurement", "by": "wei"},
        )
        assert hypothesis(out, "changeover")["grade"] == CONFIRMED

    def test_it_becomes_the_primary_cause(self):
        out = verdict(
            alarms=[alarm("manual changeover started", AFTER, "OP_STATION")],
            confirmation={"cause": "changeover", "basis": "measurement", "by": "wei"},
        )
        assert out["primary_cause"]["cause"] == "changeover"

    def test_the_timing_objection_is_kept_not_erased(self):
        """Both can be true: the person may know something the log does not, or the
        clocks may be wrong. What the tool may not do is silently pick one."""
        out = verdict(
            alarms=[alarm("manual changeover started", AFTER, "OP_STATION")],
            confirmation={"cause": "changeover", "basis": "human", "by": "wei"},
        )
        assert hypothesis(out, "changeover")["counter_evidence"]

    def test_without_a_confirmation_the_exclusion_still_stands(self):
        """The complement: promoting on timing alone would pass the tests above."""
        out = verdict(alarms=[alarm("manual changeover started", AFTER, "OP_STATION")])
        assert hypothesis(out, "changeover")["grade"] == EXCLUDED


class TestAConfirmationIsNeverSilentlyDropped:
    """The payload published a `confirmation` block while no hypothesis carried the
    grade, because a cause only becomes a hypothesis if the bundle scored it. A
    reader seeing that block concluded the verdict had been checked."""

    def _out(self):
        return verdict(
            alarms=[alarm("bearing vibration high", BEFORE, "MOTOR_01")],
            confirmation={"cause": "utility_fault", "basis": "human", "by": "wei"},
        )

    def test_the_confirmed_cause_appears_even_with_no_supporting_signal(self):
        assert hypothesis(self._out(), "utility_fault")["grade"] == CONFIRMED

    def test_it_carries_no_invented_evidence(self):
        h = hypothesis(self._out(), "utility_fault")
        assert h["evidence"] == [] and h["confidence"] == 0.0

    def test_the_mismatch_is_named_as_the_gap(self):
        """ "A person confirmed this and our evidence does not show it" is a
        finding — usually that the wrong tags were collected."""
        gaps = " ".join(hypothesis(self._out(), "utility_fault")["gaps"])
        assert "no signal supporting it" in gaps

    def test_the_payload_and_the_hypotheses_agree(self):
        out = self._out()
        assert out["confirmation"]["cause"] == "utility_fault"
        assert any(h["grade"] == CONFIRMED for h in out["hypotheses"])
