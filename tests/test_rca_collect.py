"""Live-evidence-collection tests for the RCA copilot (readers monkeypatched).

No live plant: the cross-protocol read primitives (_read_point, diagnose_dataflow,
read_alarms) are stubbed, exactly as the diagnostics tests stub connectivity. We
assert the collector shapes evidence the way downtime_rca consumes it, samples
refs into series, surfaces OPC-UA alarms only, and stays non-fatal on read errors.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain import rca_collect
from iaiops.core.runtime.config import TargetConfig


def _opcua_target(name="line1"):
    return TargetConfig(name=name, protocol="opcua", endpoint_url="opc.tcp://x:4840")


def _modbus_target(name="line2"):
    return TargetConfig(name=name, protocol="modbus", host="10.0.0.9", port=502)


@pytest.fixture
def patch_readers(monkeypatch):
    """Install deterministic stubs for the live readers; tests tune them."""
    calls = {"reads": [], "alarms": 0}

    def fake_read_point(target, ref):
        calls["reads"].append(ref)
        return 99.0, ""  # constant → flatline series

    def fake_dataflow(target, ref=None, freshness_threshold_s=60, *a, **k):
        return {"verdict": "healthy", "diagnosis": "ok"}

    monkeypatch.setattr(rca_collect, "_read_point", fake_read_point)
    monkeypatch.setattr(rca_collect, "diagnose_dataflow", fake_dataflow)
    return calls


# ─── collect_evidence ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_collect_samples_each_ref_into_series(patch_readers):
    bundle = rca_collect.collect_evidence(
        _modbus_target(),
        refs=["1", "2"],
        sample_count=5,
        interval_ms=50,
        include_alarms=False,
    )
    assert len(bundle["tags"]) == 2
    assert all(len(t["samples"]) == 5 for t in bundle["tags"])
    assert bundle["collected"]["refs_sampled"] == 2
    # 2 refs × 5 samples were actually read.
    assert len(patch_readers["reads"]) == 10


@pytest.mark.unit
def test_collected_series_feeds_tag_health_flatline(patch_readers):
    # Constant reads → tag_health should later see a flatline; here we just
    # confirm the series is well-formed numeric input.
    bundle = rca_collect.collect_evidence(
        _modbus_target(),
        refs=["1"],
        sample_count=4,
        interval_ms=50,
        include_alarms=False,
    )
    vals = [s["value"] for s in bundle["tags"][0]["samples"]]
    assert vals == [99.0, 99.0, 99.0, 99.0]


@pytest.mark.unit
def test_read_error_becomes_bad_quality_not_raise(monkeypatch):
    def boom(target, ref):
        raise ConnectionError("plc dropped")

    monkeypatch.setattr(rca_collect, "_read_point", boom)
    monkeypatch.setattr(
        rca_collect, "diagnose_dataflow", lambda *a, **k: {"verdict": "cannot_connect"}
    )
    bundle = rca_collect.collect_evidence(
        _modbus_target(), refs=["1"], sample_count=3, interval_ms=50, include_alarms=False
    )
    samples = bundle["tags"][0]["samples"]
    assert all(s["good"] is False for s in samples)
    assert "error" in samples[0]


@pytest.mark.unit
def test_alarms_only_collected_for_opcua(patch_readers, monkeypatch):
    monkeypatch.setattr(
        "iaiops.connectors.opcua.ops.read_alarms",
        lambda target, **k: {
            "active_alarms": [{"browse_name": "Motor1_Fault", "node_id": "ns=2;i=9", "value": True}]
        },
    )
    opc = rca_collect.collect_evidence(
        _opcua_target(), refs=["ns=2;i=5"], sample_count=2, interval_ms=50
    )
    mod = rca_collect.collect_evidence(_modbus_target(), refs=["1"], sample_count=2, interval_ms=50)
    assert opc["alarms"] and opc["alarms"][0]["source"] == "Motor1_Fault"
    assert opc["alarms"][0]["state"] == "ACTIVE"
    assert mod["alarms"] == []  # modbus has no active-condition surfacing


@pytest.mark.unit
def test_alarm_surfacing_failure_is_non_fatal(patch_readers, monkeypatch):
    def boom(target, **k):
        raise RuntimeError("browse failed")

    monkeypatch.setattr("iaiops.connectors.opcua.ops.read_alarms", boom)
    bundle = rca_collect.collect_evidence(
        _opcua_target(), refs=["ns=2;i=5"], sample_count=2, interval_ms=50
    )
    assert bundle["alarms"] == []  # degraded, not raised


# ─── downtime_rca_live (collect → analyze) ───────────────────────────────────


@pytest.mark.unit
def test_live_rca_runs_copilot_on_gathered_evidence(patch_readers, monkeypatch):
    monkeypatch.setattr(
        "iaiops.connectors.opcua.ops.read_alarms",
        lambda target, **k: {
            "active_alarms": [
                {"browse_name": "Drive_Fault_Trip", "node_id": "ns=2;i=9", "value": True}
            ]
        },
    )
    out = rca_collect.downtime_rca_live(
        _opcua_target(),
        window={"start": "2026-06-28T10:00:00Z", "asset": "line1"},
        refs=["ns=2;i=5"],
        sample_count=3,
        interval_ms=50,
    )
    # The surfaced "Drive_Fault" condition drives a mechanical_fault hypothesis.
    assert any(h["cause"] == "mechanical_fault" for h in out["hypotheses"])
    # Transparency: the gathered bundle tally is echoed back.
    assert out["collected_evidence"]["alarms_found"] == 1
    assert out["collected_evidence"]["refs_sampled"] == 1
    assert out["collected_evidence"]["protocol"] == "opcua"


@pytest.mark.unit
def test_live_rca_thin_evidence_is_insufficient(patch_readers):
    # healthy dataflow + a flatline-but-no-threshold tag + no alarms → thin.
    out = rca_collect.downtime_rca_live(
        _modbus_target(),
        window={"start": "2026-06-28T10:00:00Z"},
        refs=["1"],
        sample_count=3,
        interval_ms=50,
        include_alarms=False,
    )
    # A flatline tag is a real sensor signal, so it is at least surfaced...
    assert out["verdict"] in ("insufficient_evidence", "multiple_candidates")
    assert "collected_evidence" in out
