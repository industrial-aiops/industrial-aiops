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


# ── Byte-order auto-detect (pure decode logic) ──────────────────────────────


@pytest.mark.unit
def test_detect_byte_order_picks_big_endian():
    # 20.0 float32 big-endian (ABCD) == 0x41A0_0000 -> words [0x41A0, 0x0000].
    out = ops.modbus_detect_byte_order([0x41A0, 0x0000], "float32", hint=20.0)
    assert out["best"]["order"] == "ABCD"
    assert out["best"]["value"] == 20.0
    assert out["confidence"] in ("high", "medium")


@pytest.mark.unit
def test_detect_byte_order_picks_word_swap():
    # Same value laid out word-swapped (CDAB): registers swapped -> [0x0000, 0x41A0].
    out = ops.modbus_detect_byte_order([0x0000, 0x41A0], "float32", hint=20.0)
    assert out["best"]["order"] == "CDAB"
    assert out["best"]["value"] == 20.0


@pytest.mark.unit
def test_detect_byte_order_range_only():
    # 220.0 float32 big-endian == 0x435C_0000; only ABCD lands in a voltage band.
    out = ops.modbus_detect_byte_order(
        [0x435C, 0x0000], "float32", value_min=200.0, value_max=240.0
    )
    assert out["best"]["order"] == "ABCD"
    assert out["best"]["in_range"] is True


@pytest.mark.unit
def test_detect_byte_order_uint16_byte_swap():
    # 0x3412 under AB == 13330; under BA (byte-swap) == 0x1234 == 4660.
    out = ops.modbus_detect_byte_order([0x3412], "uint16", hint=4660)
    assert out["best"]["order"] == "BA"
    assert out["best"]["value"] == 4660


@pytest.mark.unit
def test_detect_byte_order_requires_a_signal():
    with pytest.raises(ValueError, match="plausibility signal"):
        ops.modbus_detect_byte_order([0x41A0, 0x0000], "float32")


@pytest.mark.unit
def test_detect_byte_order_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown value_type"):
        ops.modbus_detect_byte_order([1, 2], "float64", hint=1.0)


# ── Vendor register templates ───────────────────────────────────────────────


@pytest.mark.unit
def test_list_templates_includes_known_maps():
    out = ops.modbus_list_templates()
    names = {t["name"] for t in out["templates"]}
    assert {"generic_float32_be", "eastron_sdm630"} <= names


@pytest.mark.unit
def test_apply_template_decodes_named_tags():
    from iaiops.connectors.modbus import templates

    # generic_float32_be: f0 at offset 0; place 20.0 (0x41A0_0000) there.
    block = [0x41A0, 0x0000] + [0] * 14
    out = templates.apply_template("generic_float32_be", block, start_address=0)
    f0 = next(t for t in out["tags"] if t["tag"] == "f0")
    assert f0["value"] == 20.0
    assert f0["out_of_range"] is False


@pytest.mark.unit
def test_template_span_measured_from_base_offset():
    """An absolute-offset vendor template spans from its base, not from 0."""
    from iaiops.connectors.modbus import templates

    sch = templates.get_template("schneider_pm5xxx_basic")
    assert sch.base_offset == 2999
    assert sch.span == 112  # 3109+2-2999, NOT ~3111 (would exceed the 125-reg limit)
    gen = templates.get_template("generic_float32_be")
    assert gen.base_offset == 0
    assert gen.span == 16


@pytest.mark.unit
def test_apply_template_defaults_to_base_offset(monkeypatch):
    """With no explicit address, the read starts at the template's base offset."""
    seen = {}

    class _RecordingClient(_FakeModbusClient):
        def read_holding_registers(self, address, *, count=1, **kw):
            seen["address"] = address
            seen["count"] = count
            return _FakeResp(registers=[0] * count)

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _RecordingClient())
    target = TargetConfig(name="m", protocol="modbus", host="127.0.0.1", unit_id=1)
    ops.modbus_apply_template(target, "schneider_pm5xxx_basic")  # no address
    assert seen["address"] == 2999  # base offset, not 0
    assert seen["count"] == 112


@pytest.mark.unit
def test_apply_template_unknown_raises():
    from iaiops.connectors.modbus import templates

    with pytest.raises(KeyError, match="Unknown template"):
        templates.apply_template("does_not_exist", [0, 0])


@pytest.mark.unit
def test_apply_template_via_device(monkeypatch):
    block = [0x41A0, 0x0000] + [0] * 14
    client = _FakeModbusClient(registers=block)
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    target = TargetConfig(name="plc1", protocol="modbus", host="127.0.0.1", unit_id=7)
    out = ops.modbus_apply_template(target, "generic_float32_be", address=0)
    assert out["template"] == "generic_float32_be"
    assert out["unit_id"] == 7
    f0 = next(t for t in out["tags"] if t["tag"] == "f0")
    assert f0["value"] == 20.0


# ── Modbus-RTU (serial) transport ───────────────────────────────────────────


@pytest.mark.unit
def test_rtu_builds_serial_client(monkeypatch):
    captured: dict = {}

    class _FakeSerial:
        def __init__(self, port, *, baudrate, parity, stopbits, bytesize):
            captured.update(
                port=port, baudrate=baudrate, parity=parity, stopbits=stopbits, bytesize=bytesize
            )

    import pymodbus.client as pc

    monkeypatch.setattr(pc, "ModbusSerialClient", _FakeSerial)
    target = TargetConfig(
        name="rtu1", protocol="modbus", transport="rtu", serial_port="/dev/ttyUSB0",
        baudrate=9600, parity="E", stopbits=2, bytesize=7,
    )
    client = conn._build_modbus_client(target)
    assert isinstance(client, _FakeSerial)
    assert captured == {
        "port": "/dev/ttyUSB0", "baudrate": 9600, "parity": "E", "stopbits": 2, "bytesize": 7,
    }


@pytest.mark.unit
def test_tcp_still_builds_tcp_client(monkeypatch):
    captured: dict = {}

    class _FakeTcp:
        def __init__(self, host, *, port):
            captured.update(host=host, port=port)

    import pymodbus.client as pc

    monkeypatch.setattr(pc, "ModbusTcpClient", _FakeTcp)
    target = TargetConfig(name="tcp1", protocol="modbus", host="10.0.0.5", port=502)
    client = conn._build_modbus_client(target)
    assert isinstance(client, _FakeTcp)
    assert captured == {"host": "10.0.0.5", "port": 502}


@pytest.mark.unit
def test_rtu_missing_serial_port_is_teaching():
    target = TargetConfig(name="rtu1", protocol="modbus", transport="rtu")
    with pytest.raises(conn.OTConnectionError, match="no serial_port"):
        conn._build_modbus_client(target)


@pytest.mark.unit
def test_config_parses_rtu_serial_params():
    from iaiops.core.runtime.config import _parse_target

    t = _parse_target(
        {
            "name": "m", "protocol": "modbus", "transport": "rtu",
            "serial_port": "/dev/ttyUSB1", "baudrate": 38400, "parity": "o",
            "stopbits": 2, "bytesize": 7,
        }
    )
    assert t.transport == "rtu"
    assert t.serial_port == "/dev/ttyUSB1"
    assert t.baudrate == 38400
    assert t.parity == "O"
    assert t.stopbits == 2
    assert t.bytesize == 7


@pytest.mark.unit
def test_config_infers_rtu_from_serial_port():
    from iaiops.core.runtime.config import _parse_target

    t = _parse_target({"name": "m", "protocol": "modbus", "serial_port": "/dev/ttyS0"})
    assert t.transport == "rtu"


@pytest.mark.unit
def test_ops_read_works_over_rtu(monkeypatch):
    # The same read ops must work over the serial transport (client is faked).
    client = _FakeModbusClient(registers=[42, 0])
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    target = TargetConfig(
        name="rtu1", protocol="modbus", transport="rtu", serial_port="/dev/ttyUSB0", unit_id=5
    )
    out = ops.modbus_read_holding(target, address=0, count=1)
    assert out["raw_registers"] == [42]
    assert out["unit_id"] == 5


@pytest.mark.unit
def test_rtu_open_failure_is_teaching(monkeypatch):
    class _Down(_FakeModbusClient):
        def connect(self):
            return False

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Down())
    target = TargetConfig(
        name="rtu1", protocol="modbus", transport="rtu", serial_port="/dev/ttyUSB0"
    )
    with pytest.raises(conn.OTConnectionError, match="serial line"):
        ops.modbus_read_holding(target, address=0, count=1)


@pytest.mark.unit
def test_connect_failure_is_teaching(monkeypatch):
    class _Down(_FakeModbusClient):
        def connect(self):
            return False

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Down())
    target = TargetConfig(name="plc1", protocol="modbus", host="10.0.0.9")
    with pytest.raises(conn.OTConnectionError, match="Could not connect"):
        ops.modbus_read_holding(target, address=0, count=1)
