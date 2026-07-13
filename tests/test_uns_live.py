"""Live MQTT/Sparkplug → UNS governance bridge tests (no live broker).

Two layers are exercised deterministically:

  * The BOUNDED collector (``ops._collect``) is driven through the REAL paho
    loop by INJECTING messages through the assigned ``on_message`` callback —
    a fake client is monkeypatched in via ``connection._build_mqtt_client``. We
    assert the capture terminates on BOTH the message cap and the timeout (never
    an open-ended loop).
  * The live bridge ops (``uns_live_audit`` / ``sparkplug_live_schema`` /
    ``uns_live_drift``) are exercised with ``ops._collect`` monkeypatched to
    return synthetic messages, so the capture→govern wiring is tested without a
    broker. The Sparkplug payloads are real vendored-Tahu protobuf bytes.
"""

from __future__ import annotations

import time

import pytest

from iaiops.connectors.sparkplug import live, ops
from iaiops.core.brain import uns_governance as uns
from iaiops.core.runtime import connection
from iaiops.core.runtime.config import TargetConfig

TARGET = TargetConfig(name="uns", protocol="mqtt", host="broker", topic="spBv1.0/#")


# ─── real Sparkplug B protobuf builders (vendored Tahu schema) ────────────────


def _pb():
    from iaiops.connectors.sparkplug import sparkplug_b_pb2

    return sparkplug_b_pb2


def _nbirth(metrics: list[tuple[str, int, int]]) -> bytes:
    """NBIRTH with (name, alias, datatype) metrics."""
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 1000
    p.seq = 0
    for name, alias, dtype in metrics:
        m = p.metrics.add()
        m.name = name
        m.alias = alias
        m.datatype = dtype
    return p.SerializeToString()


# ─── bounded-collection guarantees (real loop + injected callback) ────────────


class _FakeMsg:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _SilentClient:
    """Connects fine but never delivers a message — exercises the timeout cap."""

    def __init__(self) -> None:
        self.on_message = None

    def connect(self, *args: object, **kwargs: object) -> None:
        pass

    def loop_start(self) -> None:
        pass

    def subscribe(self, topic: str) -> None:
        pass

    def loop_stop(self) -> None:
        pass

    def disconnect(self) -> None:
        pass


class _FloodClient(_SilentClient):
    """Delivers many messages synchronously on subscribe — exercises the msg cap."""

    def __init__(self, msgs: list[tuple[str, bytes]]) -> None:
        super().__init__()
        self._msgs = msgs

    def subscribe(self, topic: str) -> None:
        for topic_name, payload in self._msgs:
            if self.on_message is not None:
                self.on_message(self, None, _FakeMsg(topic_name, payload))


@pytest.mark.unit
def test_collect_times_out_and_terminates(monkeypatch):
    """No messages arriving → returns empty after the timeout, never blocks forever."""
    monkeypatch.setattr(connection, "_build_mqtt_client", lambda target: _SilentClient())
    start = time.monotonic()
    out = ops._collect(TARGET, "#", count=10, timeout_s=1)
    elapsed = time.monotonic() - start
    assert out == []
    assert elapsed < 5, "bounded capture must terminate on timeout, not block"


@pytest.mark.unit
def test_collect_stops_at_msg_cap(monkeypatch):
    """The msg cap wins over the timeout: exactly ``count`` captured, returns at once."""
    flood = [(f"factory/line/{i}", b"{}") for i in range(50)]
    monkeypatch.setattr(connection, "_build_mqtt_client", lambda target: _FloodClient(flood))
    start = time.monotonic()
    out = ops._collect(TARGET, "#", count=5, timeout_s=30)
    elapsed = time.monotonic() - start
    assert len(out) == 5, "must stop at the message cap"
    assert elapsed < 5, "must not wait for the 30s timeout once the cap is hit"
    assert out[0]["topic"] == "factory/line/0"


# ─── uns_live_audit (capture topics → uns_topic_audit) ────────────────────────


@pytest.mark.unit
def test_uns_live_audit_captures_then_audits(monkeypatch):
    msgs = [
        {"topic": "Enterprise/Site/Line1/temperature", "payload": b"1"},
        {"topic": "Enterprise/site/Line1/Temperature", "payload": b"2"},  # casing collision
        {"topic": "Enterprise/Site/Line2/temperature", "payload": b"3"},
        {"topic": "Rogue/x", "payload": b"4"},  # non-conforming root
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: list(msgs))

    out = live.uns_live_audit(
        TARGET,
        topic="#",
        duration_s=5,
        max_msgs=100,
        allowed_roots=["Enterprise"],
        min_segments=2,
    )
    assert out["capture"]["observed_messages"] == 4
    assert out["capture"]["unique_topics"] == 4
    assert out["topic_count"] == 4
    assert "Rogue" in out["findings"]["non_conforming_root"]
    assert out["findings"]["casing_collisions"], "casing collision should be flagged"


@pytest.mark.unit
def test_uns_live_audit_handles_empty_capture(monkeypatch):
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: [])
    out = live.uns_live_audit(TARGET, topic="#", duration_s=1, max_msgs=10)
    assert out["capture"]["observed_messages"] == 0
    assert "error" in out  # uns_topic_audit reports the empty list clearly


# ─── sparkplug_live_schema (capture BIRTHs → drift-ready {node:{metric:dtype}}) ─


@pytest.mark.unit
def test_sparkplug_live_schema_builds_drift_ready_dict(monkeypatch):
    msgs = [
        {
            "topic": "spBv1.0/Plant1/NBIRTH/Edge1",
            "payload": _nbirth([("Temperature", 1, 10), ("MotorRunning", 2, 11)]),
        },
        {"topic": "spBv1.0/Plant1/DBIRTH/Edge1/DevA", "payload": _nbirth([("Pressure", 3, 9)])},
        {"topic": "spBv1.0/Plant1/DDATA/Edge1/DevA", "payload": b"ignored-non-birth"},
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: list(msgs))

    out = live.sparkplug_live_schema(TARGET, topic="spBv1.0/#", duration_s=5, max_msgs=100)
    assert out["birth_count"] == 2
    assert out["node_count"] == 2
    schema = out["schema"]
    assert schema["Plant1/Edge1"] == {"Temperature": "Double", "MotorRunning": "Boolean"}
    assert schema["Plant1/Edge1/DevA"] == {"Pressure": "Float"}

    # The schema field is exactly the shape uns_schema_drift accepts.
    drift = uns.uns_schema_drift(schema, schema)
    assert drift["verdict"] == "none"


# ─── uns_live_drift (capture current live schema → compare to baseline) ───────


@pytest.mark.unit
def test_uns_live_drift_detects_breaking_change(monkeypatch):
    msgs = [
        {
            "topic": "spBv1.0/Plant1/NBIRTH/Edge1",
            "payload": _nbirth([("Temperature", 1, 4)]),
        },  # Int64 now
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: list(msgs))

    baseline = {"Plant1/Edge1": {"Temperature": "Double"}}  # was Double
    out = live.uns_live_drift(TARGET, baseline, topic="spBv1.0/#", duration_s=5, max_msgs=100)
    assert out["verdict"] == "breaking"
    assert out["capture"]["birth_count"] == 1
    changed = out["node_changes"][0]["type_changed"]
    assert changed and changed[0]["metric"] == "Temperature"
