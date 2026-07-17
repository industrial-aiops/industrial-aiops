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


def _int_metric_payload(datatype: int, field: str, wire_value: int, seq: int = 1) -> bytes:
    """One-metric payload with a raw wire value set on the given oneof field."""
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 2000
    p.seq = seq
    m = p.metrics.add()
    m.name = "T"
    m.datatype = datatype
    setattr(m, field, wire_value)
    return p.SerializeToString()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("datatype", "field", "wire", "expected"),
    [
        # Signed types arrive two's-complement in the unsigned protobuf fields
        # (int_value is uint32, long_value is uint64) and must sign-reinterpret.
        (2, "int_value", 4294967291, -5),  # Int16 −5, 32-bit-masked wire
        (2, "int_value", 65531, -5),  # Int16 −5, 16-bit-masked wire
        (1, "int_value", 255, -1),  # Int8 −1, 8-bit-masked wire
        (1, "int_value", 4294967295, -1),  # Int8 −1, 32-bit-masked wire
        (3, "int_value", (1 << 32) - 100000, -100000),  # Int32 −100000
        (4, "long_value", (1 << 64) - 7, -7),  # Int64 −7
        # Positive signed values and unsigned types must pass through unchanged.
        (2, "int_value", 5, 5),  # Int16 +5
        (4, "long_value", 7, 7),  # Int64 +7
        (6, "int_value", 65526, 65526),  # UInt16 stays unsigned
        (7, "int_value", 4294967291, 4294967291),  # UInt32 stays unsigned
        (8, "long_value", (1 << 64) - 1, (1 << 64) - 1),  # UInt64 stays unsigned
    ],
)
def test_signed_int_metrics_decode_twos_complement(datatype, field, wire, expected):
    out = ops.decode_sparkplug_payload(_int_metric_payload(datatype, field, wire))
    assert out["metrics"][0]["value"] == expected


@pytest.mark.unit
def test_float_double_boolean_untouched_by_sign_reinterpretation():
    out = ops.decode_sparkplug_payload(_birth_payload())
    names = {m["name"]: m for m in out["metrics"]}
    assert names["Temperature"]["value"] == 21.5  # Double
    assert names["MotorRunning"]["value"] is True  # Boolean


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


# ─── rich-type decode: DataSet / Template (pure codec, no broker) ─────────────
#
# DataType enums used below: Double=10, Int32=3, Int16=2, Boolean=11, String=12,
# DataSet=16, Template=19. Signed integers travel two's-complement in the
# UNSIGNED protobuf fields, so a negative cell/member/parameter is set as its
# 32-bit wire value and must sign-reinterpret through its declared column/type.
_INT32_WIRE = 1 << 32


def _add_dataset_row(dataset, cells):
    """Append a DataSet row. ``cells`` is a list of (field_name, wire_value)."""
    row = dataset.rows.add()
    for field, value in cells:
        setattr(row.elements.add(), field, value)


def _dataset_metric_payload():
    """One metric of datatype DataSet: 4 typed columns, 2 rows (incl. a −Int32)."""
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 3000
    p.seq = 2
    m = p.metrics.add()
    m.name = "ProcessTable"
    m.datatype = 16  # DataSet
    ds = m.dataset_value
    ds.num_of_columns = 4
    ds.columns.extend(["temp", "count", "running", "label"])
    ds.types.extend([10, 3, 11, 12])  # Double, Int32, Boolean, String
    _add_dataset_row(
        ds,
        [
            ("double_value", 21.5),
            ("int_value", _INT32_WIRE - 5),
            ("boolean_value", True),
            ("string_value", "ok"),
        ],
    )
    _add_dataset_row(
        ds,
        [
            ("double_value", 99.5),
            ("int_value", 7),
            ("boolean_value", False),
            ("string_value", "warn"),
        ],
    )
    return p.SerializeToString()


@pytest.mark.unit
def test_decode_dataset_columns_types_rows():
    out = ops.decode_sparkplug_payload(_dataset_metric_payload())
    metric = out["metrics"][0]
    assert metric["datatype"] == "DataSet"
    ds = metric["value"]
    assert ds["dataset"] is True
    assert ds["num_columns"] == 4
    assert ds["columns"] == ["temp", "count", "running", "label"]
    # Each column's enum type maps to its name.
    assert ds["types"] == ["Double", "Int32", "Boolean", "String"]
    assert ds["row_count"] == 2
    assert ds["truncated"] is False
    # Rows are column-aligned value lists; the −5 Int32 sign-reinterprets.
    assert ds["rows"] == [[21.5, -5, True, "ok"], [99.5, 7, False, "warn"]]


@pytest.mark.unit
def test_decode_dataset_unset_cell_is_null():
    """A DataSetValue with no oneof field set decodes to None (not a crash)."""
    pb = _pb()
    p = pb.Payload()
    m = p.metrics.add()
    m.name = "T"
    m.datatype = 16
    ds = m.dataset_value
    ds.num_of_columns = 2
    ds.columns.extend(["a", "b"])
    ds.types.extend([10, 12])
    row = ds.rows.add()
    setattr(row.elements.add(), "double_value", 1.5)
    row.elements.add()  # second element left unset
    out = ops.decode_sparkplug_payload(p.SerializeToString())
    assert out["metrics"][0]["value"]["rows"] == [[1.5, None]]


@pytest.mark.unit
def test_dataset_via_public_decode_tool_base64():
    """The rich decode surfaces through the public base64 tool path, not just internals."""
    b64 = base64.b64encode(_dataset_metric_payload()).decode()
    out = ops.sparkplug_decode_payload(b64, encoding="base64")
    rows = out["metrics"][0]["value"]["rows"]
    assert rows[0] == [21.5, -5, True, "ok"]


def _template_metric_payload():
    """One metric of datatype Template: 2 members (incl. a −Int16) + 2 parameters."""
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 4000
    p.seq = 3
    m = p.metrics.add()
    m.name = "Pump1"
    m.datatype = 19  # Template
    tpl = m.template_value
    tpl.template_ref = "PumpType"
    tpl.is_definition = False
    tpl.version = "1.0"
    mm1 = tpl.metrics.add()
    mm1.name = "flow"
    mm1.datatype = 10  # Double
    mm1.double_value = 12.5
    mm2 = tpl.metrics.add()
    mm2.name = "trim"
    mm2.datatype = 2  # Int16
    mm2.int_value = _INT32_WIRE - 40  # −40, two's-complement wire
    par1 = tpl.parameters.add()
    par1.name = "maxPressure"
    par1.type = 10  # Double
    par1.double_value = 200.0
    par2 = tpl.parameters.add()
    par2.name = "offset"
    par2.type = 3  # Int32
    par2.int_value = _INT32_WIRE - 12  # −12, two's-complement wire
    return p.SerializeToString()


@pytest.mark.unit
def test_decode_template_members_and_parameters():
    out = ops.decode_sparkplug_payload(_template_metric_payload())
    metric = out["metrics"][0]
    assert metric["datatype"] == "Template"
    tpl = metric["value"]
    assert tpl["template"] is True
    assert tpl["template_ref"] == "PumpType"
    assert tpl["is_definition"] is False
    assert tpl["version"] == "1.0"
    assert tpl["members_truncated"] is False
    # Members are {name, type, value}; the −40 Int16 member sign-reinterprets.
    assert tpl["members"] == [
        {"name": "flow", "type": "Double", "value": 12.5},
        {"name": "trim", "type": "Int16", "value": -40},
    ]
    # Parameters are type-aware; the −12 Int32 parameter sign-reinterprets.
    assert tpl["parameters"] == [
        {"name": "maxPressure", "type": "Double", "value": 200.0},
        {"name": "offset", "type": "Int32", "value": -12},
    ]


def _nested_template_payload():
    """A Template whose member is itself a Template (one level of nesting)."""
    pb = _pb()
    p = pb.Payload()
    m = p.metrics.add()
    m.name = "Skid"
    m.datatype = 19
    outer = m.template_value
    outer.template_ref = "SkidType"
    pump = outer.metrics.add()
    pump.name = "pump"
    pump.datatype = 19  # Template
    inner = pump.template_value
    inner.template_ref = "PumpType"
    leaf = inner.metrics.add()
    leaf.name = "flow"
    leaf.datatype = 10
    leaf.double_value = 3.3
    return p.SerializeToString()


@pytest.mark.unit
def test_decode_nested_template_recurses():
    out = ops.decode_sparkplug_payload(_nested_template_payload())
    outer = out["metrics"][0]["value"]
    assert outer["template_ref"] == "SkidType"
    pump_member = outer["members"][0]
    assert pump_member["name"] == "pump"
    assert pump_member["type"] == "Template"
    # The nested Template member expanded, not stringified.
    inner = pump_member["value"]
    assert inner["template_ref"] == "PumpType"
    assert inner["members"] == [{"name": "flow", "type": "Double", "value": 3.3}]


def _deeply_nested_template(levels: int):
    """Chain ``levels`` Templates, each carrying the next as its sole member."""
    pb = _pb()
    p = pb.Payload()
    m = p.metrics.add()
    m.name = "L0"
    m.datatype = 19
    cur = m.template_value
    cur.template_ref = "L0"
    for i in range(1, levels):
        child = cur.metrics.add()
        child.name = f"L{i}"
        child.datatype = 19
        cur = child.template_value
        cur.template_ref = f"L{i}"
    return p.SerializeToString()


@pytest.mark.unit
def test_nested_template_depth_guard_terminates():
    """Pathological deep nesting is bounded — decode terminates and flags truncation."""
    out = ops.decode_sparkplug_payload(_deeply_nested_template(ops.MAX_TEMPLATE_DEPTH + 4))
    node = out["metrics"][0]["value"]
    depth = 0
    while node.get("template") and node.get("members"):
        node = node["members"][0]["value"]
        depth += 1
    # Recursion halted at the ceiling with members omitted, not stack-overflowed.
    assert depth == ops.MAX_TEMPLATE_DEPTH
    assert node["members"] == []
    assert node["members_truncated"] is True


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
def test_rebirth_resets_seq_tracking_without_false_gap(monkeypatch):
    """An NBIRTH restarts the node's seq at 0 (Sparkplug spec) — no gap flagged."""
    msgs = [
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": _birth_payload(seq=0)},
        {"topic": "spBv1.0/Plant1/NDATA/Edge1", "payload": _data_payload(seq=1, value=22.0)},
        # Rebirth: seq restarts at 0 — this is NOT a gap.
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": _birth_payload(seq=0)},
        {"topic": "spBv1.0/Plant1/NDATA/Edge1", "payload": _data_payload(seq=1, value=23.0)},
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: msgs)
    out = ops.sparkplug_node_list(TARGET)
    node = next(n for n in out["nodes"] if n["edge_node_id"] == "Edge1")
    assert node["seq_gap_count"] == 0
    assert node["seq_issues"] == []


@pytest.mark.unit
def test_genuine_gap_after_rebirth_still_flagged(monkeypatch):
    """Resetting on NBIRTH must not hide a real mid-stream seq gap."""
    msgs = [
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": _birth_payload(seq=0)},
        {"topic": "spBv1.0/Plant1/NDATA/Edge1", "payload": _data_payload(seq=1, value=22.0)},
        {"topic": "spBv1.0/Plant1/NBIRTH/Edge1", "payload": _birth_payload(seq=0)},
        # Genuine gap after the rebirth: 0 → 5.
        {"topic": "spBv1.0/Plant1/NDATA/Edge1", "payload": _data_payload(seq=5, value=23.0)},
    ]
    monkeypatch.setattr(ops, "_collect", lambda t, topic, count, timeout_s: msgs)
    out = ops.sparkplug_node_list(TARGET)
    node = next(n for n in out["nodes"] if n["edge_node_id"] == "Edge1")
    assert node["seq_gap_count"] == 1
    assert node["seq_issues"][0]["expected"] == 1
    assert node["seq_issues"][0]["got"] == 5


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
