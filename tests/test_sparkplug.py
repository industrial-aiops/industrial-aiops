"""MQTT / Sparkplug B ops tests with synthetic payloads (no live broker).

The bounded collector ``_collect`` is monkeypatched to return synthetic messages,
so payload decoding, Sparkplug topic parsing, node discovery, UNS browse, and the
publish dry-run gate are all exercised without a broker.
"""

from __future__ import annotations

import base64

import pytest

from iaiops.connectors.sparkplug import ops
from iaiops.core.runtime.config import TargetConfig

TARGET = TargetConfig(name="uns", protocol="mqtt", host="broker", topic="spBv1.0/#")


# ─── synthetic Sparkplug B protobuf builders (vendored Tahu schema) ───────────


def _pb():
    from iaiops.connectors.sparkplug import sparkplug_b_pb2

    return sparkplug_b_pb2


def _birth_payload(seq=0):
    """NBIRTH with two named+aliased metrics (a Double and a Boolean)."""
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 1000
    p.seq = seq
    m1 = p.metrics.add()
    m1.name = "Temperature"
    m1.alias = 1
    m1.datatype = 10  # Double
    m1.double_value = 21.5
    m2 = p.metrics.add()
    m2.name = "MotorRunning"
    m2.alias = 2
    m2.datatype = 11  # Boolean
    m2.boolean_value = True
    return p.SerializeToString()


def _data_payload(seq=1, value=22.0, historical=False):
    """NDATA with an alias-only metric (no name) — needs the birth alias map."""
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 2000
    p.seq = seq
    m = p.metrics.add()
    m.alias = 1
    m.datatype = 10
    m.double_value = value
    m.is_historical = historical
    return p.SerializeToString()


@pytest.mark.unit
def test_decode_sparkplug_payload_full():
    out = ops.decode_sparkplug_payload(_birth_payload())
    assert out["encoding"] == "sparkplug_b"
    assert out["seq"] == 0
    assert out["metric_count"] == 2
    names = {m["name"]: m for m in out["metrics"]}
    assert names["Temperature"]["datatype"] == "Double"
    assert names["Temperature"]["value"] == 21.5
    assert names["MotorRunning"]["datatype"] == "Boolean"
    assert names["MotorRunning"]["value"] is True


@pytest.mark.unit
def test_decode_resolves_alias_from_birth_map():
    out = ops.decode_sparkplug_payload(_data_payload(value=23.4), alias_map={1: "Temperature"})
    assert out["metrics"][0]["name"] == "Temperature"
    assert out["metrics"][0]["value"] == 23.4


@pytest.mark.unit
def test_decode_payload_tool_base64_and_hex():
    raw = _birth_payload()
    b64 = base64.b64encode(raw).decode()
    out_b64 = ops.sparkplug_decode_payload(b64, encoding="base64")
    out_hex = ops.sparkplug_decode_payload(raw.hex(), encoding="hex")
    assert out_b64["metric_count"] == 2
    assert out_hex["metric_count"] == 2


@pytest.mark.unit
def test_historical_flag_decoded():
    out = ops.decode_sparkplug_payload(_data_payload(historical=True), alias_map={1: "Temperature"})
    assert out["metrics"][0]["is_historical"] is True
    assert out["historical_count"] == 1


@pytest.mark.unit
def test_subscribe_sample_birth_data_model(monkeypatch):
    msgs = [
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": _birth_payload(seq=0)},
        {"topic": "spBv1.0/Plant1/NDATA/Edge1", "payload": _data_payload(seq=1, value=22.0)},
        # seq jumps 1 → 5 (gap)
        {"topic": "spBv1.0/Plant1/NDATA/Edge1", "payload": _data_payload(seq=5, value=23.0)},
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: msgs)
    out = ops.sparkplug_subscribe_sample(TARGET)
    assert out["message_count"] == 3
    assert out["seq_gap_count"] >= 1  # the 1→5 jump flagged
    # The alias-only NDATA resolved its name from the BIRTH model.
    data_sample = out["samples"][1]["payload"]
    assert data_sample["metrics"][0]["name"] == "Temperature"


@pytest.mark.unit
def test_node_list_online_and_seq(monkeypatch):
    msgs = [
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": _birth_payload(seq=0)},
        {"topic": "spBv1.0/Plant1/DBIRTH/Edge1/DevA", "payload": _birth_payload(seq=1)},
        {"topic": "spBv1.0/STATE/primaryHost", "payload": b'{"online": true}'},
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: msgs)
    out = ops.sparkplug_node_list(TARGET)
    node = next(n for n in out["nodes"] if n["edge_node_id"] == "Edge1")
    assert node["online"] is True
    assert node["born"] is True
    assert "DevA" in node["devices"]
    assert out["primary_hosts"][0]["host_id"] == "primaryHost"
    assert out["primary_hosts"][0]["state"] == "ONLINE"


@pytest.mark.unit
def test_decode_json_payload():
    out = ops._decode_payload(b'{"temp": 21.5}')
    assert out["encoding"] == "json"
    assert out["json"]["temp"] == 21.5


@pytest.mark.unit
def test_decode_text_payload():
    out = ops._decode_payload(b"AVAILABLE")
    assert out["encoding"] == "text"
    assert out["text"] == "AVAILABLE"


@pytest.mark.unit
def test_decode_binary_payload_is_not_fatal():
    out = ops._decode_payload(b"\x08\x96\x01\x12\x07metric")
    assert out["encoding"] in ("binary", "sparkplug_b")
    if out["encoding"] == "binary":
        assert "hex_preview" in out and "note" in out


@pytest.mark.unit
def test_parse_sparkplug_topic():
    p = ops._parse_sparkplug_topic("spBv1.0/Plant1/NBIRTH/EdgeNode5/Dev2")
    assert p["group_id"] == "Plant1"
    assert p["message_type"] == "NBIRTH"
    assert p["edge_node_id"] == "EdgeNode5"
    assert p["device_id"] == "Dev2"
    assert ops._parse_sparkplug_topic("factory/line1/temp") is None


def _fake_messages():
    return [
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": b'{"online": true}'},
        {"topic": "spBv1.0/Plant1/DBIRTH/Edge1/DevA", "payload": b'{"x": 1}'},
        {"topic": "spBv1.0/Plant1/DDATA/Edge1/DevA", "payload": b'{"x": 2}'},
        {"topic": "spBv1.0/Plant2/NBIRTH/Edge9", "payload": b'{"online": true}'},
    ]


@pytest.fixture
def patched_collect(monkeypatch):
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: _fake_messages())


@pytest.mark.unit
def test_sparkplug_node_list(patched_collect):
    out = ops.sparkplug_node_list(TARGET)
    keys = {(n["group_id"], n["edge_node_id"]) for n in out["nodes"]}
    assert ("Plant1", "Edge1") in keys
    assert ("Plant2", "Edge9") in keys
    plant1 = next(n for n in out["nodes"] if n["edge_node_id"] == "Edge1")
    assert plant1["born"] is True
    assert "DevA" in plant1["devices"]


@pytest.mark.unit
def test_uns_browse_builds_tree(patched_collect):
    out = ops.uns_browse(TARGET, topic="spBv1.0/#")
    assert out["topic_count"] == 4
    assert "spBv1.0" in out["tree"]
    assert "Plant1" in out["tree"]["spBv1.0"]


@pytest.mark.unit
def test_mqtt_read_topic_decodes(patched_collect):
    out = ops.mqtt_read_topic(TARGET, topic="spBv1.0/#")
    assert out["message_count"] == 4
    assert out["messages"][0]["payload"]["encoding"] == "json"


@pytest.mark.unit
def test_sparkplug_subscribe_sample_parses_topic(patched_collect):
    out = ops.sparkplug_subscribe_sample(TARGET)
    assert out["samples"][1]["sparkplug"]["message_type"] == "DBIRTH"


@pytest.mark.unit
def test_mqtt_publish_dry_run_does_not_publish():
    out = ops.mqtt_publish(TARGET, "factory/cmd", '{"setpoint": 50}', dry_run=True)
    assert out["dry_run"] is True
    assert out["would_publish_bytes"] > 0
    assert "未经授权" in out["note"]
