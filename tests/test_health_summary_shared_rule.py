"""#249 follow-up 1: both health summaries share one rule, and say how much they saw.

0.29.0 stopped the headline reading ``ok`` with unknown points. Two gaps were
left. A real alarm wins the headline, which is right — but then nothing in the
headline says that other points were never judged, so "alarm on 1 point" over a
tag list where 9 of 10 reads failed read like the only problem. And Modbus
``ch:<name>`` profile channels were sent through ``parse_point``, which raises on
them, so every profile channel came back ``unknown`` — the summary could not
judge the very points the sensor layer was built to read.
"""

from __future__ import annotations

import contextlib
import struct

import pytest

from iaiops.connectors.modbus import ops
from iaiops.core.brain import analysis
from iaiops.core.brain._shared import health_overall
from iaiops.core.runtime import connection as conn
from iaiops.core.runtime.config import MonitorTag, TargetConfig
from iaiops.core.runtime.sensor import parse_profile

pytestmark = pytest.mark.unit


def _counts(ok=0, warn=0, alarm=0, unknown=0):
    return {"ok": ok, "warn": warn, "alarm": alarm, "unknown": unknown}


@pytest.mark.parametrize(
    ("counts", "overall", "coverage"),
    [
        (_counts(ok=3), "ok", "complete"),
        (_counts(ok=2, unknown=1), "unknown", "partial"),
        (_counts(unknown=2), "unknown", "none"),
        (_counts(alarm=1, unknown=9), "alarm", "partial"),
        (_counts(warn=1, ok=1, unknown=1), "warn", "partial"),
        (_counts(alarm=1, ok=2), "alarm", "complete"),
        (_counts(), "unknown", "none"),
    ],
)
def test_the_one_rule(counts, overall, coverage):
    assert health_overall(counts) == {"overall": overall, "coverage": coverage}


def test_ok_is_never_the_headline_with_an_unjudged_point():
    for ok in range(3):
        assert health_overall(_counts(ok=ok, unknown=1))["overall"] != "ok"


class _Resp:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):  # noqa: N802 — pymodbus API
        return False


def _f32_cdab(value: float) -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    return [(c << 8) | d, (a << 8) | b]


class _Client:
    """Holding 0 = 20; input 4..5 = Fz as float32 CDAB."""

    def __init__(self, fz: float = 250.0):
        self.fz = fz
        self.input_calls: list[tuple[int, int]] = []

    def connect(self):
        return True

    def close(self):
        return None

    def read_holding_registers(self, address, *, count=1, device_id=1, **kw):
        return _Resp([20] * count)

    def read_input_registers(self, address, *, count=1, device_id=1, **kw):
        self.input_calls.append((address, count))
        return _Resp(_f32_cdab(self.fz)[:count])


FORCE = parse_profile(
    {
        "id": "force",
        "protocol": "modbus",
        "source": "manual",
        "verified": "待核实",
        "channels": [
            {
                "name": "fz",
                "layout": {"table": "input", "address": 4, "type": "float32", "order": "CDAB"},
                "unit": "N",
                "range": [-300, 300],
                "signal": "level",
            }
        ],
    }
)


@pytest.fixture
def force_profile(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: FORCE)


def _modbus_target(*tags: MonitorTag, profile: str = "force.yaml") -> TargetConfig:
    return TargetConfig(
        name="cell", protocol="modbus", host="127.0.0.1", sensor_profile=profile, tags=tags
    )


def test_modbus_summary_judges_a_profile_channel(monkeypatch, force_profile):
    client = _Client(fz=250.0)
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    out = ops.modbus_health_summary(_modbus_target(MonitorTag(ref="ch:fz", warn_high=200)))
    (entry,) = out["results"]
    assert entry["status"] == "warn", entry
    assert entry["value"] == pytest.approx(250.0)
    assert entry["address"] == 4
    assert client.input_calls == [(4, 2)]  # the profile's table, address and width
    assert out["overall"] == "warn" and out["coverage"] == "complete"


def test_modbus_profile_channel_out_of_range_is_unknown_with_its_reason(monkeypatch, force_profile):
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client(fz=999.0))
    out = ops.modbus_health_summary(_modbus_target(MonitorTag(ref="ch:fz")))
    (entry,) = out["results"]
    assert entry["status"] == "unknown"
    assert "range" in entry["reason"]


def test_modbus_profile_channel_without_a_profile_is_unknown_and_says_why(monkeypatch):
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client())
    out = ops.modbus_health_summary(_modbus_target(MonitorTag(ref="ch:fz"), profile=""))
    (entry,) = out["results"]
    assert entry["status"] == "unknown"
    assert "sensor_profile" in entry["reason"]
    assert out["overall"] == "unknown" and out["coverage"] == "none"


def test_modbus_alarm_with_unjudged_points_says_partial(monkeypatch):
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Client())
    target = TargetConfig(
        name="plc1",
        protocol="modbus",
        host="127.0.0.1",
        tags=(MonitorTag(ref="0", alarm_high=10), MonitorTag(ref="not-an-address")),
    )
    out = ops.modbus_health_summary(target)
    assert (out["overall"], out["coverage"]) == ("alarm", "partial")


def test_opcua_alarm_with_unjudged_points_says_partial(monkeypatch):
    values = {"ns=2;s=a": {"value": 99}, "ns=2;s=b": {"error": "BadNodeIdUnknown"}}
    monkeypatch.setattr(analysis, "opcua_session", lambda target: contextlib.nullcontext(None))
    monkeypatch.setattr(analysis, "_read_one", lambda client, ref: values[ref])
    target = TargetConfig(
        name="srv",
        protocol="opcua",
        host="127.0.0.1",
        tags=(MonitorTag(ref="ns=2;s=a", alarm_high=50), MonitorTag(ref="ns=2;s=b")),
    )
    out = analysis.health_summary(target)
    assert (out["overall"], out["coverage"]) == ("alarm", "partial")
