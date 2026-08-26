"""A tag we could not read says nothing about the sensor behind it.

Found 2026-08-26 by running the flagship command the way a plant would — "the
line stopped this morning, tell me why" — against an endpoint that was switched
off, which is the ordinary case: the incident is over and nobody has powered the
cell back up.

Every read failed with `Connection refused`. `_sample_tag` recorded each failure
as a bad-quality sample (its comment said so in as many words: *"a per-read
failure is bad-quality data"*), the ranker scored two bad-quality tags at 0.45
each, and the verdict was:

    primary_cause: sensor_fault, confidence 0.70
    recommended_action: Field-verify the sensor/transmitter and wiring.

The sensors were fine. The tool could not reach the device, and turned its own
blindness into a fault at the plant — then dispatched somebody to check wiring.

**It knew.** `dataflow_verdict` was already `cannot_connect`, and `comms_loss`
was already a candidate at 0.60. It lost, because a dead transport manufactures
one bad-quality signal PER REF while the truth gets a single dataflow signal:

    refs | primary       | sensor_fault | comms_loss
    -----+---------------+--------------+-----------
     0   | comms_loss ✓  | 0.0000       | 0.6000
     1   | comms_loss ✓  | 0.4500       | 0.6000
     2   | sensor_fault ✗| 0.6975       | 0.6000
     3   | sensor_fault ✗| 0.8336       | 0.6000

Confidence that the plant's sensors are broken as a function of how many tags
you asked about. That monotonicity is the proof it is an artifact, and it is
what the first test below pins.

This is the defect class the codebase exists to refuse — an error pointing in
the direction that makes the customer's problem look worse and the tool look
more useful. The OEE path already gets the same question right: blind time is
excluded rather than counted as downtime. This is that rule, one layer up.

The fix is at COLLECTION, not scoring: evidence we never obtained is not
manufactured in the first place. `downtime_rca` itself is unchanged, so a
hand-authored bundle carrying genuine bad-quality readings still scores exactly
as before.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.rca_collect import collect_evidence, downtime_rca_live

pytestmark = pytest.mark.unit

WINDOW = {"start": "2026-08-26T07:48:12Z", "end": "2026-08-26T07:48:27Z", "asset": "Line 1"}


#: `_read_point` dispatches on `target.protocol` through the capability
#: registry, so a fake object's own methods are never called — the seam has to
#: be the dispatcher itself, or the test quietly talks to the network.
REFUSED = "Connection to (192.168.60.74, 15020) failed: [Errno 61] Connection refused"


class _Endpoint:
    name = "line1"
    protocol = "modbus"

    def tag_for(self, _ref):
        return None


@pytest.fixture
def unreachable(monkeypatch):
    """An endpoint that is switched off — every read raises, as pymodbus does,
    and the dataflow probe reports what it found."""

    def _boom(_target, _ref):
        raise ConnectionError(REFUSED)

    monkeypatch.setattr("iaiops.core.brain.rca_collect._read_point", _boom)
    monkeypatch.setattr(
        "iaiops.core.brain.rca_collect.diagnose_dataflow",
        lambda *_a, **_k: {
            "verdict": "cannot_connect",
            "detail": "Could not reach the endpoint — likely network path down, PLC off.",
        },
    )
    return _Endpoint()


@pytest.fixture
def reachable(monkeypatch):
    """The complement: a device that ANSWERS. `ref == "bad"` answers with a bad
    value, which is real evidence; nothing here raises."""

    def _read(_target, ref):
        return (None if ref == "bad" else 2.0), ""

    monkeypatch.setattr("iaiops.core.brain.rca_collect._read_point", _read)
    monkeypatch.setattr(
        "iaiops.core.brain.rca_collect.diagnose_dataflow",
        lambda *_a, **_k: {"verdict": "ok", "detail": "reachable"},
    )
    return _Endpoint()


def _verdict(target, refs, **kw) -> dict:
    return downtime_rca_live(target, WINDOW, refs=refs, sample_count=2, interval_ms=1, **kw)


def _confidence(out: dict, cause: str) -> float:
    for h in out["hypotheses"]:
        if h["cause"] == cause:
            return float(h["confidence"])
    return 0.0


class TestOurOwnBlindnessIsNotAFaultAtThePlant:
    @pytest.mark.parametrize(
        "refs", [["0"], ["0", "10"], ["0", "10", "11"], ["0", "10", "11", "1"]]
    )
    def test_an_unreachable_endpoint_never_reads_as_a_sensor_fault(self, unreachable, refs):
        """Parametrized over ref COUNT on purpose: the defect was monotone in it,
        so a single-ref example would have passed while two refs still lied."""
        out = _verdict(unreachable, refs)
        assert _confidence(out, "sensor_fault") == 0.0, out["hypotheses"]

    @pytest.mark.parametrize("refs", [["0"], ["0", "10"], ["0", "10", "11"]])
    def test_the_answer_is_the_true_one_whatever_the_ref_count(self, unreachable, refs):
        out = _verdict(unreachable, refs)
        assert out["primary_cause"] is not None
        assert out["primary_cause"]["cause"] == "comms_loss", out["primary_cause"]

    def test_confidence_does_not_grow_with_the_number_of_tags_we_failed_to_read(self, unreachable):
        """The property, stated directly. Asking about more tags cannot make us
        more certain of anything when we read none of them."""
        scores = [
            _confidence(_verdict(unreachable, ["0", "10", "11"][:n]), "sensor_fault")
            for n in (1, 2, 3)
        ]
        assert scores == [0.0, 0.0, 0.0], scores

    def test_it_never_tells_anyone_to_go_and_check_wiring(self, unreachable):
        """The behavioural cost. The old verdict sent an engineer to field-verify
        a transmitter that was not broken."""
        out = _verdict(unreachable, ["0", "10", "11"])
        text = str(out["primary_cause"]).lower()
        assert "wiring" not in text and "transmitter" not in text, out["primary_cause"]


class TestItSaysWhatItCouldNotRead:
    """Dropping the false evidence is half of it. Silently dropping it would
    leave the operator thinking three tags were examined and found innocent."""

    def test_the_unreadable_refs_are_named(self, unreachable):
        bundle = collect_evidence(unreachable, ["0", "10"], sample_count=2, interval_ms=1)
        assert {t["ref"] for t in bundle["unreadable"]} == {"0", "10"}

    def test_each_one_carries_the_reason(self, unreachable):
        bundle = collect_evidence(unreachable, ["0"], sample_count=2, interval_ms=1)
        assert "refused" in bundle["unreadable"][0]["error"].lower()

    def test_the_tally_counts_what_was_obtained_not_what_was_attempted(self, unreachable):
        """`refs_sampled: 3` on a run where zero reads succeeded is the same lie
        in smaller print."""
        bundle = collect_evidence(unreachable, ["0", "10", "11"], sample_count=2, interval_ms=1)
        assert bundle["collected"]["refs_sampled"] == 0
        assert bundle["collected"]["refs_requested"] == 3
        assert bundle["collected"]["refs_unreadable"] == 3

    def test_the_verdict_carries_it_too(self, unreachable):
        """`collected_evidence` is what a reader of the JSON actually sees."""
        out = _verdict(unreachable, ["0", "10"])
        assert out["collected_evidence"]["refs_unreadable"] == 2


class TestARealReadingIsStillEvidence:
    """The complement, and the one that stops the fix from becoming its own
    defect: refusing every tag would pass every test above and make the copilot
    blind to real sensor faults."""

    def test_a_reachable_endpoint_still_produces_tag_evidence(self, reachable):
        bundle = collect_evidence(reachable, ["0", "10"], sample_count=2, interval_ms=1)
        assert len(bundle["tags"]) == 2
        assert bundle["unreadable"] == []
        assert bundle["collected"]["refs_sampled"] == 2

    def test_a_tag_that_answers_with_a_bad_value_is_kept(self, reachable):
        """`good: False` from a device that ANSWERED is real bad-quality data —
        exactly the signal sensor_fault is for. Only an unanswered read is
        excluded."""
        bundle = collect_evidence(reachable, ["bad"], sample_count=2, interval_ms=1)
        assert len(bundle["tags"]) == 1
        assert all(sample["good"] is False for sample in bundle["tags"][0]["samples"])
        assert bundle["unreadable"] == []

    def test_a_partly_readable_tag_is_kept_whole(self, monkeypatch):
        """One dropped read inside an otherwise answering series is ordinary
        jitter, not a reason to discard the series."""
        calls = {"n": 0}

        def _flaky(_target, _ref):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return 2.0, ""

        monkeypatch.setattr("iaiops.core.brain.rca_collect._read_point", _flaky)
        monkeypatch.setattr(
            "iaiops.core.brain.rca_collect.diagnose_dataflow",
            lambda *_a, **_k: {"verdict": "ok", "detail": "reachable"},
        )
        bundle = collect_evidence(_Endpoint(), ["0"], sample_count=3, interval_ms=1)
        assert len(bundle["tags"]) == 1
        assert bundle["unreadable"] == []

    def test_the_scoring_engine_itself_is_untouched(self):
        """A hand-authored bundle with bad-quality tags must score as it always
        did — the fix is at collection, and `downtime_rca` serves callers that
        never went near a device."""
        from iaiops.core.brain.rca import downtime_rca

        out = downtime_rca(
            WINDOW,
            tags=[
                {"ref": "0", "samples": [{"value": None, "good": False}]},
                {"ref": "10", "samples": [{"value": None, "good": False}]},
            ],
        )
        assert _confidence(out, "sensor_fault") > 0.0
