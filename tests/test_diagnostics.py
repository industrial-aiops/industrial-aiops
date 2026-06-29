"""Cross-protocol diagnostics tests over synthetic data (no live systems).

Exercises the flatline/stale/flood/anomaly classification logic with crafted
series and event lists, plus diagnose_dataflow's hop localization via a mocked
connectivity probe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import diagnostics as diag
from iaiops.core.runtime.config import TargetConfig


def _iso(dt):
    return dt.isoformat()


# ─── historian_health ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_historian_flatline():
    out = diag.historian_health([{"value": 5.0} for _ in range(10)])
    assert out["flatline"] is True
    assert out["verdict"] == "flatline"


@pytest.mark.unit
def test_historian_bad_tag():
    out = diag.historian_health([{"value": None, "good": False} for _ in range(5)])
    assert out["bad_quality_count"] == 5
    assert out["verdict"] == "bad_tag"


@pytest.mark.unit
def test_historian_gaps():
    now = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)
    series = [
        {"value": 1, "timestamp": _iso(now)},
        {"value": 2, "timestamp": _iso(now + timedelta(seconds=5))},
        {"value": 3, "timestamp": _iso(now + timedelta(seconds=600))},  # 595s gap
    ]
    out = diag.historian_health(series, gap_threshold_s=60)
    assert out["gap_count"] == 1
    assert out["verdict"] == "gappy"


# ─── alarm_bad_actors (ISA-18.2) ─────────────────────────────────────────────


@pytest.mark.unit
def test_alarm_flood_and_pareto():
    now = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)
    events = []
    # FIC101 floods (50 alarms in ~50s), others sparse
    for i in range(50):
        events.append({"source": "FIC101", "timestamp": _iso(now + timedelta(seconds=i)),
                       "priority": "high", "state": "ACTIVE"})
    for i in range(5):
        events.append({"source": f"TI{i}", "timestamp": _iso(now + timedelta(seconds=i * 2)),
                       "priority": "low"})
    out = diag.alarm_bad_actors(events)
    assert out["flood_verdict"] == "flood"
    assert out["top_offenders"][0]["source"] == "FIC101"
    assert "FIC101" in out["pareto_sources_for_80pct"]
    assert "FIC101" in out["chattering"]


@pytest.mark.unit
def test_alarm_rate_ok():
    now = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)
    events = [{"source": "A", "timestamp": _iso(now + timedelta(minutes=20 * i))}
              for i in range(3)]
    out = diag.alarm_bad_actors(events)
    assert out["flood_verdict"] in ("ok", "manageable")


@pytest.mark.unit
def test_alarm_empty_returns_error():
    assert "error" in diag.alarm_bad_actors([])


# ─── tag_health ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tag_health_ranks_offenders():
    tags = [
        {"ref": "ok_tag", "samples": [10, 11, 12, 11, 10]},
        {"ref": "flat", "samples": [5, 5, 5, 5, 5]},
        {"ref": "hot", "samples": [70, 71, 70, 99], "warn_high": 80, "alarm_high": 95},
        {"ref": "bad", "samples": [{"value": None, "good": False}]},
    ]
    out = diag.tag_health(tags)
    refs = [o["ref"] for o in out["offenders"]]
    assert "ok_tag" not in refs
    assert {"flat", "hot", "bad"} <= set(refs)
    assert out["overall"] == "alarm"
    hot = next(o for o in out["offenders"] if o["ref"] == "hot")
    assert "out_of_range_alarm" in hot["flags"]


@pytest.mark.unit
def test_tag_health_detects_statistical_anomaly():
    # A single large spike over a realistic bounded window (z-score > 3σ).
    tags = [{"ref": "spike", "samples": [10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.0,
                                         10.3, 9.7, 10.0, 200.0]}]
    out = diag.tag_health(tags)
    spike = out["results"][0]
    assert "statistical_anomaly" in spike["flags"]
    assert spike["anomaly_count"] >= 1


# ─── diagnose_dataflow ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_diagnose_cannot_connect(monkeypatch):
    monkeypatch.setattr(diag, "_probe_connect", lambda t: (False, "timed out"))
    target = TargetConfig(name="x", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    out = diag.diagnose_dataflow(target)
    assert out["verdict"] == "cannot_connect"
    assert out["hops"][0]["hop"] == "connect"


@pytest.mark.unit
def test_diagnose_stale_value(monkeypatch):
    old = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    monkeypatch.setattr(diag, "_probe_connect", lambda t: (True, "ok"))
    monkeypatch.setattr(diag, "_read_ref",
                        lambda t, ref: {"value": 5.0, "good": True, "source_timestamp": old})
    target = TargetConfig(name="x", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    out = diag.diagnose_dataflow(target, ref="ns=2;i=5", freshness_threshold_s=60)
    assert out["verdict"] == "comms_ok_value_stale"


@pytest.mark.unit
def test_diagnose_flatline(monkeypatch):
    now = datetime.now(tz=UTC).isoformat()
    monkeypatch.setattr(diag, "_probe_connect", lambda t: (True, "ok"))
    monkeypatch.setattr(diag, "_read_ref",
                        lambda t, ref: {"value": 5.0, "good": True, "source_timestamp": now})
    target = TargetConfig(name="x", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    out = diag.diagnose_dataflow(target, ref="ns=2;i=5", series=[5.0] * 10)
    assert out["verdict"] == "comms_ok_flatline"


@pytest.mark.unit
def test_diagnose_bad_quality(monkeypatch):
    now = datetime.now(tz=UTC).isoformat()
    monkeypatch.setattr(diag, "_probe_connect", lambda t: (True, "ok"))
    monkeypatch.setattr(diag, "_read_ref",
                        lambda t, ref: {"value": 5.0, "good": False, "source_timestamp": now})
    target = TargetConfig(name="x", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    out = diag.diagnose_dataflow(target, ref="ns=2;i=5")
    assert out["verdict"] == "comms_ok_bad_quality"
