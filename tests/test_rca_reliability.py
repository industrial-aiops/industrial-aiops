"""How much history stands behind a ranking, reported beside how confident it is.

ROADMAP §3 / D24: *90% from a site with three recorded cases is not 90% from a
site with three hundred.* The verdict carried `confidence_band` and nothing about
its basis, so a reader had to supply the second number from imagination — and
imagination is generous.

Getting there uncovered a second thing. `diag rca --weights` documents its input
as "e.g. from `diag learn-weights`", and `learn_cause_weights` returns
`{cause_weights, n_incidents, per_cause, rationale}`. Feeding that straight back
in failed:

    Error: cause_weights['cause_weights'] is not a known cause

The two commands the help text composes did not compose, and a user had to
hand-extract the inner map. Unwrapping the profile fixes that AND recovers
`n_incidents`, which is the number reliability needs — the fix and the feature
turned out to be the same change.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.rca import downtime_rca
from iaiops.core.brain.rca_weights import learn_cause_weights

pytestmark = pytest.mark.unit

WINDOW = {"start": "2026-08-24T01:00:00Z", "end": "2026-08-24T01:10:00Z"}
TAGS = [{"ref": "T1", "samples": [{"value": 1, "good": False}] * 3}]


def _profile(per_cause: int) -> dict:
    corpus = [{"cause": "comms_loss", "signals": ["comms_loss"]}] * per_cause
    corpus += [{"cause": "sensor_fault", "signals": ["sensor_fault"]}] * per_cause
    return learn_cause_weights(corpus)


def _verdict(**kwargs) -> dict:
    return downtime_rca(WINDOW, tags=TAGS, **kwargs)


class TestALearnerProfileFeedsStraightBackIn:
    def test_the_whole_profile_is_accepted(self):
        """It used to raise: 'cause_weights' is not a known cause."""
        assert _verdict(cause_weights=_profile(12))["verdict"]

    def test_a_bare_map_still_works(self):
        """The older calling convention must not break."""
        assert _verdict(cause_weights={"comms_loss": 1.5})["verdict"]

    def test_an_unknown_cause_inside_a_profile_is_still_refused(self):
        """Unwrapping must not become a hole in the boundary validation."""
        with pytest.raises(ValueError) as excinfo:
            _verdict(cause_weights={"cause_weights": {"not_a_cause": 1.5}, "n_incidents": 9})
        assert "not a known cause" in str(excinfo.value)


class TestReliabilityRidesBesideConfidence:
    def test_no_weights_means_shipped_defaults(self):
        rel = _verdict()["reliability"]
        assert rel["basis"] == "shipped_defaults"
        assert rel["cases"] is None

    def test_a_learned_profile_reports_its_case_count(self):
        rel = _verdict(cause_weights=_profile(12))["reliability"]
        assert rel["basis"] == "site_profile"
        assert rel["cases"] == 24

    def test_a_thin_history_says_how_thin(self):
        """The most useful case: the learner kept the defaults, and the reader is
        told the site has two cases rather than being left to assume hundreds."""
        rel = _verdict(cause_weights=_profile(1))["reliability"]
        assert rel["basis"] == "shipped_defaults"
        assert rel["cases"] == 2
        assert "2 confirmed incident(s)" in rel["note"]

    def test_a_bare_map_admits_its_basis_is_unknown(self):
        """Weights given as a raw map carry no history with them, and saying
        nothing would read as 'learned from a lot'."""
        rel = _verdict(cause_weights={"comms_loss": 1.5})["reliability"]
        assert rel["basis"] == "site_profile"
        assert rel["cases"] is None
        assert "unknown" in rel["note"]

    def test_reliability_is_not_confidence(self):
        """Two different questions. The note says so, because a reader who
        conflates them reads a tuned ranking as a verified one."""
        rel = _verdict(cause_weights=_profile(12))["reliability"]
        assert "different things" in rel["note"]

    def test_it_is_present_on_every_verdict_shape(self):
        """Including the thin-evidence one — that is where a reader most needs to
        know whether the ranking rests on anything."""
        for kwargs in ({}, {"tags": []}, {"cause_weights": _profile(12)}):
            out = downtime_rca(WINDOW, **{"tags": TAGS, **kwargs})
            assert out["reliability"]["basis"]
