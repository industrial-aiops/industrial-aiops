"""AI downtime root-cause copilot tests over synthetic evidence (no live systems).

Exercises temporal correlation (cause-before-effect), multi-stream agreement
(noisy-OR confidence compounding), the anti-hallucination downgrade to
'insufficient_evidence', and the advisory/read-only contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import rca

ONSET = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _window(**extra) -> dict:
    return {"start": _iso(ONSET), "end": _iso(ONSET + timedelta(minutes=5)),
            "asset": "line1", **extra}


# ─── regression: review fixes ────────────────────────────────────────────────


@pytest.mark.unit
def test_naive_window_with_aware_alarm_does_not_crash():
    # The common OT case: operator types a naive start, device alarm carries Z.
    naive_window = {"start": "2026-06-28T10:00:00", "asset": "line1"}
    aware_alarm = [{"source": "M1_DRIVE", "timestamp": "2026-06-28T09:59:55Z",
                    "message": "motor overload trip"}]
    out = rca.downtime_rca(naive_window, alarms=aware_alarm)
    assert out["verdict"] != "insufficient_evidence"  # it ran, no TypeError
    assert out["primary_cause"]["cause"] == "mechanical_fault"


@pytest.mark.unit
def test_chattering_same_source_does_not_inflate_confidence():
    # One source firing 5× must count as ONE piece of evidence, not five.
    chatter = [{"source": "FEED1", "timestamp": _iso(ONSET - timedelta(seconds=5 + i)),
                "message": "infeed starved"} for i in range(5)]
    single = [{"source": "FEED1", "timestamp": _iso(ONSET - timedelta(seconds=5)),
               "message": "infeed starved"}]
    c_chatter = rca.downtime_rca(_window(), alarms=chatter)["hypotheses"][0]["confidence"]
    c_single = rca.downtime_rca(_window(), alarms=single)["hypotheses"][0]["confidence"]
    assert c_chatter == c_single  # deduped per (source, cause)
    # and the cited evidence is a single material_starvation entry
    h = rca.downtime_rca(_window(), alarms=chatter)["hypotheses"][0]
    assert h["cause"] == "material_starvation"
    assert len(h["evidence"]) == 1


@pytest.mark.unit
def test_end_before_start_is_error():
    bad = {"start": _iso(ONSET), "end": _iso(ONSET - timedelta(minutes=5))}
    out = rca.downtime_rca(bad, alarms=[{"source": "M1", "timestamp": _iso(ONSET),
                                         "message": "jam"}])
    assert out["verdict"] == "insufficient_evidence"
    assert "error" in out


# ─── window resolution ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_missing_start_is_error():
    out = rca.downtime_rca({"asset": "x"})
    assert out["verdict"] == "insufficient_evidence"
    assert "error" in out


@pytest.mark.unit
def test_window_end_derived_from_state_series():
    series = [
        {"timestamp": _iso(ONSET - timedelta(seconds=10)), "state": "RUNNING"},
        {"timestamp": _iso(ONSET), "state": "FAULT"},
        {"timestamp": _iso(ONSET + timedelta(seconds=120)), "state": "RUNNING"},
    ]
    out = rca.downtime_rca({"start": _iso(ONSET)}, state_series=series)
    assert out["window"]["duration_s"] is not None
    # The FAULT state seeds a mechanical prior even with no other evidence.
    assert any(h["cause"] == "mechanical_fault" for h in out["hypotheses"])


# ─── single-cause identification ─────────────────────────────────────────────


@pytest.mark.unit
def test_mechanical_trigger_before_onset_dominates():
    alarms = [{
        "source": "M1_DRIVE", "timestamp": _iso(ONSET - timedelta(seconds=8)),
        "message": "motor overload trip", "priority": "high", "state": "ACTIVE",
    }]
    tags = [{"ref": "DRV1.Torque", "samples": [10, 11, 99, 99],
             "warn_high": 50, "alarm_high": 80}]
    out = rca.downtime_rca(_window(), alarms=alarms, tags=tags,
                           dataflow={"verdict": "healthy"})
    assert out["primary_cause"]["cause"] == "mechanical_fault"
    assert out["primary_cause"]["confidence_band"] == "high"
    # Two independent streams agree → confidence compounds above either alone.
    assert out["primary_cause"]["confidence"] > rca.W_ALARM_TRIGGER
    assert out["verdict"] == "root_cause_identified"


@pytest.mark.unit
def test_evidence_cites_only_real_signals():
    alarms = [{"source": "FEED1", "timestamp": _iso(ONSET - timedelta(seconds=5)),
               "message": "infeed starved — no part"}]
    out = rca.downtime_rca(_window(), alarms=alarms)
    primary = out["primary_cause"]
    assert primary["cause"] == "material_starvation"
    refs = [c["ref"] for c in primary["evidence"]]
    assert "FEED1" in refs  # cited signal is exactly the supplied one
    assert all("weight" in c for c in primary["evidence"])


@pytest.mark.unit
def test_comms_loss_from_dataflow_verdict():
    out = rca.downtime_rca(
        _window(),
        dataflow={"verdict": "cannot_connect", "diagnosis": "no route to PLC"},
    )
    assert out["primary_cause"]["cause"] == "comms_loss"
    assert out["primary_cause"]["evidence"][0]["signal"] == "dataflow"


# ─── temporal logic ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_alarm_after_onset_is_weaker_than_before():
    before = [{"source": "M1_DRIVE", "timestamp": _iso(ONSET - timedelta(seconds=5)),
               "message": "drive fault"}]
    after = [{"source": "M1_DRIVE", "timestamp": _iso(ONSET + timedelta(seconds=5)),
              "message": "drive fault"}]
    c_before = rca.downtime_rca(_window(), alarms=before)["hypotheses"][0]["confidence"]
    c_after = rca.downtime_rca(_window(), alarms=after)["hypotheses"][0]["confidence"]
    assert c_before > c_after


@pytest.mark.unit
def test_alarm_outside_lead_window_is_discounted():
    near = [{"source": "M1", "timestamp": _iso(ONSET - timedelta(seconds=10)),
             "message": "mechanical jam"}]
    far = [{"source": "M1", "timestamp": _iso(ONSET - timedelta(seconds=290)),
            "message": "mechanical jam"}]
    c_near = rca.downtime_rca(_window(), alarms=near, lead_window_s=300)
    c_far = rca.downtime_rca(_window(), alarms=far, lead_window_s=300)
    assert c_near["hypotheses"][0]["confidence"] > c_far["hypotheses"][0]["confidence"]


# ─── multi-candidate + anti-hallucination ────────────────────────────────────


@pytest.mark.unit
def test_conflicting_streams_yield_multiple_candidates():
    alarms = [{"source": "M1", "timestamp": _iso(ONSET - timedelta(seconds=5)),
               "message": "mechanical jam"}]
    out = rca.downtime_rca(
        _window(), alarms=alarms,
        dataflow={"verdict": "comms_ok_value_stale", "diagnosis": "stale"},
    )
    causes = {h["cause"] for h in out["hypotheses"]}
    assert {"mechanical_fault", "sensor_fault"} <= causes
    assert out["verdict"] in ("multiple_candidates", "root_cause_identified")


@pytest.mark.unit
def test_no_evidence_is_insufficient_with_next_data():
    out = rca.downtime_rca(_window())
    assert out["verdict"] == "insufficient_evidence"
    assert out["primary_cause"] is None
    assert out["recommended_next_data"]
    assert any("Alarm" in s for s in out["recommended_next_data"])


@pytest.mark.unit
def test_flood_only_does_not_invent_a_cause():
    # A pure alarm flood with no classifiable trigger is context, not a root cause.
    flood = [{"source": f"X{i % 3}", "timestamp": _iso(ONSET - timedelta(seconds=i)),
              "message": "high", "state": "ACTIVE"} for i in range(60)]
    out = rca.downtime_rca(_window(), alarms=flood)
    assert out["verdict"] == "insufficient_evidence"
    assert "alarm_flood" in {h["cause"] for h in out["hypotheses"]}


@pytest.mark.unit
def test_weak_single_signal_not_high_confidence():
    # One minor, untimed tag offender must not masquerade as a confident root cause.
    tags = [{"ref": "T1", "samples": [
        {"value": 10, "good": True}, {"value": 12, "good": True},
        {"value": 11, "good": False},  # some_bad_quality → minor, severity 1
    ]}]
    out = rca.downtime_rca(_window(), tags=tags)
    top = out["hypotheses"][0]
    assert top["confidence_band"] == "low"
    assert out["verdict"] == "insufficient_evidence"


# ─── contract guarantees ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_output_is_advisory_and_read_only():
    out = rca.downtime_rca(
        _window(),
        alarms=[{"source": "M1", "timestamp": _iso(ONSET), "message": "drive trip"}],
    )
    assert "advisory" in out["anti_hallucination"].lower()
    for h in out["hypotheses"]:
        assert h["recommended_action"]  # every hypothesis carries a next step
    # Confidence is always a bounded probability.
    for h in out["hypotheses"]:
        assert 0.0 <= h["confidence"] <= 1.0


@pytest.mark.unit
def test_evidence_summary_is_honest_about_inputs():
    out = rca.downtime_rca(
        _window(),
        alarms=[{"source": "M1", "timestamp": _iso(ONSET), "message": "jam"}],
        tags=[{"ref": "T1", "samples": [1, 1, 1, 1]}],
    )
    summ = out["evidence_summary"]
    assert summ["alarms_supplied"] == 1
    assert summ["tags_supplied"] == 1
    assert summ["total_evidence_items"] >= 1
