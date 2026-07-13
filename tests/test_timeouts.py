"""Connect timeouts: TargetConfig.timeout_s is threaded into every client builder.

Without an explicit timeout a dead endpoint blocks on the OS TCP timeout
(60-120s+); these tests pin the fix by monkeypatching each pinned client class
and asserting the configured timeout reaches it.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime import connection
from iaiops.core.runtime.config import (
    DEFAULT_TIMEOUT_S,
    TIMEOUT_ENV_VAR,
    TargetConfig,
    _parse_target,
)

# ─── config parsing ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_timeout_defaults_to_ten_seconds():
    target = TargetConfig(name="t", protocol="modbus", host="h")
    assert target.timeout_s == DEFAULT_TIMEOUT_S == 10.0


@pytest.mark.unit
def test_timeout_parsed_from_config_entry():
    target = _parse_target({"name": "x", "protocol": "modbus", "host": "h", "timeout_s": 3})
    assert target.timeout_s == 3.0


@pytest.mark.unit
def test_timeout_alias_key_accepted():
    target = _parse_target({"name": "x", "protocol": "modbus", "host": "h", "timeout": 2.5})
    assert target.timeout_s == 2.5


@pytest.mark.unit
def test_invalid_timeout_falls_back_to_default(monkeypatch):
    monkeypatch.delenv(TIMEOUT_ENV_VAR, raising=False)
    for bad in ("abc", -1, 0):
        target = _parse_target(
            {"name": "x", "protocol": "modbus", "host": "h", "timeout_s": bad}
        )
        assert target.timeout_s == DEFAULT_TIMEOUT_S


@pytest.mark.unit
def test_timeout_env_var_sets_fleet_default(monkeypatch):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "7")
    target = _parse_target({"name": "x", "protocol": "modbus", "host": "h"})
    assert target.timeout_s == 7.0


@pytest.mark.unit
def test_timeout_env_var_invalid_ignored(monkeypatch):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "not-a-number")
    target = _parse_target({"name": "x", "protocol": "modbus", "host": "h"})
    assert target.timeout_s == DEFAULT_TIMEOUT_S


@pytest.mark.unit
def test_config_entry_overrides_env_default(monkeypatch):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "7")
    target = _parse_target({"name": "x", "protocol": "modbus", "host": "h", "timeout_s": 4})
    assert target.timeout_s == 4.0


# ─── builder wiring ───────────────────────────────────────────────────────────


class _FakeOpcuaClient:
    """Records the constructor timeout; supports the auth/security setters."""

    def __init__(self, url: str, timeout: float = 4, **kwargs) -> None:
        self.url = url
        self.timeout = timeout

    def set_user(self, username: str) -> None:  # pragma: no cover — not hit here
        pass

    def set_password(self, password: str) -> None:  # pragma: no cover
        pass

    def set_security_string(self, sec: str) -> None:  # pragma: no cover
        pass


@pytest.mark.unit
def test_opcua_builder_passes_timeout(monkeypatch):
    import asyncua.sync

    monkeypatch.setattr(asyncua.sync, "Client", _FakeOpcuaClient)
    monkeypatch.setattr(TargetConfig, "password", lambda self: "")
    target = TargetConfig(
        name="t", protocol="opcua", endpoint_url="opc.tcp://plc:4840", timeout_s=3.5
    )
    client = connection._build_opcua_client(target)
    assert client.timeout == 3.5


class _FakeS7Client:
    """Records every constructor kwarg."""

    def __init__(self, address: str, **kwargs) -> None:
        self.address = address
        self.kwargs = kwargs


@pytest.mark.unit
def test_s7_builder_passes_timeout(monkeypatch):
    import pyS7

    monkeypatch.setattr(pyS7, "S7Client", _FakeS7Client)
    target = TargetConfig(name="t", protocol="s7", host="10.0.0.9", timeout_s=6.0)
    client = connection._build_s7_client(target)
    assert client.kwargs["timeout"] == 6.0


class _FakeType3E:
    """pymcprotocol has no constructor timeout; ``soc_timeout`` is the knob."""

    def __init__(self, plctype: str = "Q") -> None:
        self.plctype = plctype
        self.soc_timeout = 2  # the library default


@pytest.mark.unit
def test_mc_builder_sets_soc_timeout(monkeypatch):
    import pymcprotocol

    monkeypatch.setattr(pymcprotocol, "Type3E", _FakeType3E)
    target = TargetConfig(name="t", protocol="mc", host="10.0.0.9", timeout_s=8.0)
    client = connection._build_mc_client(target)
    assert client.soc_timeout == 8.0


class _FakeLogixDriver:
    """pycomm3 exposes ``socket_timeout`` as a public property."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.socket_timeout = 5.0  # the library default


@pytest.mark.unit
def test_eip_builder_sets_socket_timeout(monkeypatch):
    import pycomm3

    monkeypatch.setattr(pycomm3, "LogixDriver", _FakeLogixDriver)
    target = TargetConfig(
        name="t", protocol="ethernetip", host="10.0.0.9", slot=0, timeout_s=4.5
    )
    client = connection._build_eip_client(target)
    assert client.socket_timeout == 4.5


class _FakeModbusTcpClient:
    """Records the constructor timeout (pymodbus defaults to 3s without it)."""

    def __init__(self, host: str, *, port: int, timeout: float = 3) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout


@pytest.mark.unit
def test_modbus_tcp_builder_passes_timeout(monkeypatch):
    import pymodbus.client as pc

    monkeypatch.setattr(pc, "ModbusTcpClient", _FakeModbusTcpClient)
    target = TargetConfig(name="t", protocol="modbus", host="10.0.0.9", timeout_s=4.0)
    client = connection._build_modbus_client(target)
    assert client.timeout == 4.0


class _FakeModbusSerialClient:
    """Records the constructor timeout for the RTU (serial) transport."""

    def __init__(self, port: str, *, baudrate: int, parity: str, stopbits: int,
                 bytesize: int, timeout: float = 3) -> None:
        self.port = port
        self.timeout = timeout


@pytest.mark.unit
def test_modbus_serial_builder_passes_timeout(monkeypatch):
    import pymodbus.client as pc

    monkeypatch.setattr(pc, "ModbusSerialClient", _FakeModbusSerialClient)
    target = TargetConfig(
        name="t", protocol="modbus", transport="rtu", serial_port="/dev/ttyUSB0", timeout_s=6.5
    )
    client = connection._build_modbus_client(target)
    assert client.timeout == 6.5
