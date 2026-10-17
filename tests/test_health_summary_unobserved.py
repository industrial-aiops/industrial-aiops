"""A health summary may say ``ok`` only about what it observed.

Pre-release audit: both classifiers reported ``overall: ok`` while points could
not be classified — the OPC UA one even when NO point could be (every read
failed). Unobserved is not healthy; with nothing in warn/alarm and anything
unknown, the headline is ``unknown``.
"""

from __future__ import annotations

import contextlib

import pytest

from iaiops.connectors.modbus import ops
from iaiops.core.brain import analysis
from iaiops.core.runtime import connection as conn
from iaiops.core.runtime.config import MonitorTag, TargetConfig

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):  # noqa: N802 — pymodbus API
        return False


class _Client:
    def connect(self):
        return True

    def close(self):
        return None

    def read_holding_registers(self, address, *, count=1, device_id=1, **kw):
        return _Resp([20] * count)


def test_modbus_one_point_unobserved_is_not_ok(monkeypatch):
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client())
    target = TargetConfig(
        name="plc1",
        protocol="modbus",
        host="127.0.0.1",
        tags=(MonitorTag(ref="0", warn_high=70), MonitorTag(ref="not-an-address")),
    )
    out = ops.modbus_health_summary(target)
    assert out["counts"] == {"ok": 1, "warn": 0, "alarm": 0, "unknown": 1}
    assert out["overall"] == "unknown"


def test_modbus_a_real_alarm_still_wins_over_unknowns(monkeypatch):
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client())
    target = TargetConfig(
        name="plc1",
        protocol="modbus",
        host="127.0.0.1",
        tags=(MonitorTag(ref="0", alarm_high=10), MonitorTag(ref="not-an-address")),
    )
    assert ops.modbus_health_summary(target)["overall"] == "alarm"


def _opcua(monkeypatch, values: dict) -> TargetConfig:
    monkeypatch.setattr(analysis, "opcua_session", lambda target: contextlib.nullcontext(None))
    monkeypatch.setattr(analysis, "_read_one", lambda client, ref: values[ref])
    return TargetConfig(name="srv", protocol="opcua", host="127.0.0.1")


def test_opcua_every_read_failed_is_not_ok(monkeypatch):
    target = _opcua(monkeypatch, {"ns=2;s=a": {"error": "BadNodeIdUnknown"}})
    out = analysis.health_summary(target, ["ns=2;s=a"])
    assert out["counts"]["unknown"] == 1
    assert out["overall"] == "unknown"


def test_opcua_all_observed_and_in_band_is_ok(monkeypatch):
    target = _opcua(monkeypatch, {"ns=2;s=a": {"value": 20}})
    assert analysis.health_summary(target, ["ns=2;s=a"])["overall"] == "ok"
