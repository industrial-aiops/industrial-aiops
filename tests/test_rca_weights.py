"""Per-site RCA cause-weight adaptation tests (PURE, no live systems).

Covers the two new capabilities layered onto the downtime root-cause copilot:

  * a ``cause_weights`` override on ``downtime_rca`` that re-weights per-cause
    evidence WITHOUT changing the default (no-override) behaviour, and
  * ``learn_cause_weights`` — a pure, explainable estimator that derives a
    per-site ``{cause: weight}`` profile from a labeled incident corpus, with
    smoothing + a min-sample guard and a fall-back to defaults on thin history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import rca
from iaiops.core.brain.rca_weights import learn_cause_weights

ONSET = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _window(**extra) -> dict:
    return {"start": _iso(ONSET), "end": _iso(ONSET + timedelta(minutes=5)),
            "asset": "line1", **extra}


def _starve_alarm() -> list[dict]:
    return [{"source": "FEED1", "timestamp": _iso(ONSET - timedelta(seconds=5)),
             "message": "infeed starved — no part"}]


# ─── override: back-compat (defaults unchanged) ──────────────────────────────


@pytest.mark.unit
def test_no_override_equals_none_equals_empty():
    base = rca.downtime_rca(_window(), alarms=_starve_alarm())
    none = rca.downtime_rca(_window(), alarms=_starve_alarm(), cause_weights=None)
    empty = rca.downtime_rca(_window(), alarms=_starve_alarm(), cause_weights={})
    assert base == none == empty  # absent override ⇒ today's behaviour exactly


# ─── override: shifts the verdict in the expected direction ───────────────────


@pytest.mark.unit
def test_boosting_a_cause_raises_its_confidence_and_promotes_verdict():
    base = rca.downtime_rca(_window(), alarms=_starve_alarm())
    boosted = rca.downtime_rca(_window(), alarms=_starve_alarm(),
                               cause_weights={"material_starvation": 1.6})
    assert base["verdict"] == "multiple_candidates"
    assert boosted["verdict"] == "root_cause_identified"
    assert (boosted["primary_cause"]["confidence"]
            > base["primary_cause"]["confidence"])


@pytest.mark.unit
def test_deboosting_a_cause_downgrades_to_insufficient():
    deboosted = rca.downtime_rca(_window(), alarms=_starve_alarm(),
                                 cause_weights={"material_starvation": 0.3})
    assert deboosted["verdict"] == "insufficient_evidence"


@pytest.mark.unit
def test_override_can_flip_the_primary_cause():
    alarms = [{"source": "M1_DRIVE", "timestamp": _iso(ONSET - timedelta(seconds=5)),
               "message": "mechanical jam"}]
    dataflow = {"verdict": "comms_ok_value_stale", "diagnosis": "stale"}
    base = rca.downtime_rca(_window(), alarms=alarms, dataflow=dataflow)
    assert base["primary_cause"]["cause"] == "mechanical_fault"
    flipped = rca.downtime_rca(_window(), alarms=alarms, dataflow=dataflow,
                               cause_weights={"sensor_fault": 1.6})
    assert flipped["primary_cause"]["cause"] == "sensor_fault"


@pytest.mark.unit
def test_override_is_deterministic():
    a = rca.downtime_rca(_window(), alarms=_starve_alarm(),
                         cause_weights={"material_starvation": 1.4})
    b = rca.downtime_rca(_window(), alarms=_starve_alarm(),
                         cause_weights={"material_starvation": 1.4})
    assert a == b


# ─── override: validation / clamping at the boundary ─────────────────────────


@pytest.mark.unit
def test_unknown_cause_in_override_is_a_teaching_error():
    with pytest.raises(ValueError, match="known cause"):
        rca.downtime_rca(_window(), alarms=_starve_alarm(),
                         cause_weights={"gremlins": 2.0})


@pytest.mark.unit
def test_non_numeric_override_is_a_teaching_error():
    with pytest.raises(ValueError, match="number"):
        rca.downtime_rca(_window(), alarms=_starve_alarm(),
                         cause_weights={"material_starvation": "lots"})


@pytest.mark.unit
def test_override_weight_is_clamped_not_unbounded():
    huge = rca.downtime_rca(_window(), alarms=_starve_alarm(),
                            cause_weights={"material_starvation": 1000.0})
    at_max = rca.downtime_rca(_window(), alarms=_starve_alarm(),
                              cause_weights={"material_starvation": rca.MAX_CAUSE_WEIGHT})
    assert huge == at_max  # clamped, so absurd input ≡ the cap


# ─── learn_cause_weights: recovers a known weighting ─────────────────────────


def _corpus(reliable_n: int, noisy_n: int) -> list[dict]:
    """mechanical_fault evidence is always right; comms_loss evidence misleads."""
    reliable = [{"cause": "mechanical_fault", "signals": ["mechanical_fault"]}
                for _ in range(reliable_n)]
    noisy = [{"cause": "mechanical_fault", "signals": ["comms_loss"]}
             for _ in range(noisy_n)]
    return reliable + noisy


@pytest.mark.unit
def test_learn_recovers_reliable_above_noisy():
    out = learn_cause_weights(_corpus(10, 10))
    weights = out["cause_weights"]
    assert weights["mechanical_fault"] > 1.0  # trustworthy evidence is up-weighted
    assert weights["comms_loss"] < 1.0        # misleading evidence is down-weighted
    assert weights["mechanical_fault"] > weights["comms_loss"]
    assert out["rationale"]
    assert out["per_cause"]["mechanical_fault"]["support"] == 10


@pytest.mark.unit
def test_learn_is_deterministic():
    a = learn_cause_weights(_corpus(9, 7))
    b = learn_cause_weights(_corpus(9, 7))
    assert a == b


@pytest.mark.unit
def test_learn_thin_history_falls_back_to_defaults():
    out = learn_cause_weights([{"cause": "mechanical_fault",
                                "signals": ["mechanical_fault"]}] * 3)
    assert out["cause_weights"] == {}  # no per-site adaptation
    assert "thin" in out["rationale"].lower()


@pytest.mark.unit
def test_learn_min_sample_guard_keeps_rare_cause_neutral():
    corpus = _corpus(10, 0) + [
        {"cause": "quality_reject", "signals": ["quality_reject"]},
        {"cause": "quality_reject", "signals": ["quality_reject"]},
    ]  # quality_reject observed only twice (< min per-cause samples)
    out = learn_cause_weights(corpus)
    assert "quality_reject" not in out["cause_weights"]  # too few samples → neutral
    assert "mechanical_fault" in out["cause_weights"]


@pytest.mark.unit
def test_learn_does_not_mutate_input():
    corpus = _corpus(6, 6)
    snapshot = [dict(inc) for inc in corpus]
    learn_cause_weights(corpus)
    assert corpus == snapshot


@pytest.mark.unit
def test_learn_rejects_non_list():
    with pytest.raises(ValueError, match="list"):
        learn_cause_weights({"cause": "mechanical_fault"})


@pytest.mark.unit
def test_learn_rejects_unknown_cause_label():
    with pytest.raises(ValueError, match="known cause"):
        learn_cause_weights([{"cause": "gremlins", "signals": []}] * 8)


# ─── learn → apply round trip ────────────────────────────────────────────────


@pytest.mark.unit
def test_learned_weights_feed_back_into_rca():
    learned = learn_cause_weights(_corpus(12, 0))["cause_weights"]
    alarms = [{"source": "M1_DRIVE", "timestamp": _iso(ONSET - timedelta(seconds=5)),
               "message": "mechanical jam"}]
    base = rca.downtime_rca(_window(), alarms=alarms)
    tuned = rca.downtime_rca(_window(), alarms=alarms, cause_weights=learned)
    assert (tuned["primary_cause"]["confidence"]
            >= base["primary_cause"]["confidence"])
