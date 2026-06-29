"""Modbus ops tests against a mocked pymodbus client.

A real Modbus server is heavier to stand up than asyncua's in-process server, so
the pymodbus client is faked by monkeypatching ``connection._build_modbus_client``.
This still exercises the full session / decode / threshold-classifier path.
"""

from __future__ import annotations

import struct

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.modbus import ops
from iaiops.core.runtime.config import MonitorTag, TargetConfig


class _FakeResp:
    def __init__(self, registers=None, bits=None, error=False):
        self.registers = registers or []
        self.bits = bits or []
        self._error = error

    def isError(self):  # noqa: N802 — mirrors pymodbus's response API
        return self._error


class _FakeModbusClient:
    """Minimal pymodbus ModbusTcpClient double (read-only)."""

    def __init__(self, registers=None, bits=None):
        self._registers = registers or [25, 0]
        self._bits = bits if bits is not None else [True, False, True]

    def connect(self):
        return True

    def close(self):
        return None

    def read_holding_registers(self, address, *, count=1, device_id=1, no_response_expected=False):
        return _FakeResp(registers=self._registers[:count])

    def read_input_registers(self, address, *, count=1, device_id=1, no_response_expected=False):
        return _FakeResp(registers=self._registers[:count])

    def read_coils(self, address, *, count=1, device_id=1, no_response_expected=False):
        return _FakeResp(bits=self._bits[:count])

    def read_discrete_inputs(self, address, *, count=1, device_id=1, no_response_expected=False):
        return _FakeResp(bits=self._bits[:count])


@pytest.fixture
def modbus_target(monkeypatch):
    client = _FakeModbusClient(registers=[25, 0, 0x41A0, 0x0000])
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    return TargetConfig(name="plc1", protocol="modbus", host="127.0.0.1", port=502, unit_id=3)


@pytest.mark.unit
def test_read_holding_uint16(modbus_target):
    out = ops.modbus_read_holding(modbus_target, address=0, count=1)
    assert out["raw_registers"] == [25]
    assert out["decoded"] == [25]
    assert out["unit_id"] == 3


@pytest.mark.unit
def test_read_holding_float32_decode(modbus_target):
    # 0x41A0_0000 big-endian float32 == 20.0
    out = ops.modbus_read_holding(modbus_target, address=2, count=2, decode="float32")
    # the fake returns the first `count` registers, i.e. [25, 0] -> decode those
    expected = round(struct.unpack(">f", struct.pack(">HH", 25, 0))[0], 6)
    assert out["decoded"][0] == expected


@pytest.mark.unit
def test_read_coils(modbus_target):
    out = ops.modbus_read_coils(modbus_target, address=0, count=3)
    assert out["bits"] == [True, False, True]


@pytest.mark.unit
def test_read_discrete(modbus_target):
    out = ops.modbus_read_discrete(modbus_target, address=0, count=2)
    assert out["bits"] == [True, False]


@pytest.mark.unit
def test_read_error_is_teaching(monkeypatch):
    client = _FakeModbusClient()
    client.read_holding_registers = lambda address, **kw: _FakeResp(error=True)
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    target = TargetConfig(name="plc1", protocol="modbus", host="127.0.0.1")
    with pytest.raises(conn.OTConnectionError, match="address 5 failed"):
        ops.modbus_read_holding(target, address=5, count=1)


@pytest.mark.unit
def test_modbus_health_summary_classifies(monkeypatch):
    client = _FakeModbusClient(registers=[95])
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    target = TargetConfig(
        name="plc1",
        protocol="modbus",
        host="127.0.0.1",
        tags=(MonitorTag(ref="0", label="temp", warn_high=70, alarm_high=90),),
    )
    out = ops.modbus_health_summary(target)
    assert out["overall"] == "alarm"  # 95 >= alarm_high 90
    assert out["counts"]["alarm"] == 1
    assert out["offenders"][0]["address"] == 0


@pytest.mark.unit
def test_modbus_health_summary_no_tags_returns_error(monkeypatch):
    client = _FakeModbusClient()
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    target = TargetConfig(name="plc1", protocol="modbus", host="127.0.0.1")
    out = ops.modbus_health_summary(target)
    assert "error" in out


@pytest.mark.unit
def test_connect_failure_is_teaching(monkeypatch):
    class _Down(_FakeModbusClient):
        def connect(self):
            return False

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Down())
    target = TargetConfig(name="plc1", protocol="modbus", host="10.0.0.9")
    with pytest.raises(conn.OTConnectionError, match="Could not connect"):
        ops.modbus_read_holding(target, address=0, count=1)
