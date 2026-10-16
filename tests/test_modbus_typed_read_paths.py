"""Every Modbus read path honours a typed point — collect, monitor and read_ref.

Three paths existed, each hard-coding ``read_holding_registers(int(ref), count=1)``.
Fixing one and not the others would make the same ref mean different things
depending on which command read it.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from iaiops.core.runtime import capabilities as caps
from iaiops.core.runtime.session_factory import OTNoReadingError


def _f32(value: float) -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    return [(a << 8) | b, (c << 8) | d]


class _Resp:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):  # noqa: N802 — pymodbus API
        return False


class _Client:
    iaiops_unit_id = 3

    def __init__(self, words):
        self.words = words
        self.calls = []

    def read_holding_registers(self, address, count, device_id):
        self.calls.append(("holding", address, count, device_id))
        return _Resp(self.words[:count])

    def read_input_registers(self, address, count, device_id):
        self.calls.append(("input", address, count, device_id))
        return _Resp(self.words[:count])


@pytest.mark.unit
def test_session_read_decodes_a_typed_input_float():
    client = _Client(_f32(12.5))
    value, ts = caps._session_read_modbus(client, "ir:4:float32:ABCD")
    assert value == pytest.approx(12.5) and ts == ""
    assert client.calls == [("input", 4, 2, 3)]


@pytest.mark.unit
def test_session_read_legacy_ref_is_unchanged():
    client = _Client([0xFFFF])
    value, _ = caps._session_read_modbus(client, "12")
    assert value == 0xFFFF
    assert client.calls == [("holding", 12, 1, 3)]


@pytest.mark.unit
def test_session_read_turns_an_invalid_reading_into_a_gap_not_a_disconnect():
    """A NaN from a healthy device is no reading — the session must stay up."""
    client = _Client(_f32(float("nan")))
    with pytest.raises(OTNoReadingError):
        caps._session_read_modbus(client, "ir:0:float32:ABCD")


def _fake_ops(monkeypatch, words):
    calls = []

    def holding(target, address, count=1, decode="uint16"):
        calls.append(("holding", address, count, decode))
        return {"raw_registers": words[:count], "decoded": words[:count]}

    def inputs(target, address, count=1, decode="uint16"):
        calls.append(("input", address, count, decode))
        return {"raw_registers": words[:count], "decoded": words[:count]}

    import iaiops.connectors.modbus.ops as ops

    monkeypatch.setattr(ops, "modbus_read_holding", holding)
    monkeypatch.setattr(ops, "modbus_read_input", inputs)
    return calls


@pytest.mark.unit
def test_monitor_read_decodes_a_typed_point(monkeypatch):
    calls = _fake_ops(monkeypatch, _f32(-3.0))
    value, _ = caps._monitor_modbus(SimpleNamespace(), "hr:0:float32:ABCD")
    assert value == pytest.approx(-3.0)
    assert calls == [("holding", 0, 2, "raw")]


@pytest.mark.unit
def test_read_ref_decodes_a_typed_point(monkeypatch):
    _fake_ops(monkeypatch, [250])
    out = caps._readref_modbus(SimpleNamespace(), "ir:1:int16*0.1")
    assert out == {"value": pytest.approx(25.0), "good": True}


@pytest.mark.unit
def test_read_ref_reports_an_invalid_reading_as_not_good(monkeypatch):
    _fake_ops(monkeypatch, _f32(float("inf")))
    out = caps._readref_modbus(SimpleNamespace(), "ir:1:float32:ABCD")
    assert out["good"] is False and out["value"] is None and "finite" in out["reason"]


@pytest.mark.unit
def test_legacy_monitor_read_is_unchanged(monkeypatch):
    calls = _fake_ops(monkeypatch, [7])
    value, _ = caps._monitor_modbus(SimpleNamespace(), "9")
    assert value == 7
    assert calls == [("holding", 9, 1, "uint16")]
