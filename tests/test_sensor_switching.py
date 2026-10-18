"""E2b (HLD §17.5b, D59–D61): switching sensors — NPN / PNP / dry contact.

They reach iaiops through a PLC or a Modbus DI module. A switching point is
`di:<addr>:<high|low>` (FC02) or `co:<addr>:<high|low>` (FC01), or a profile
channel with `layout: {table: discrete|coil, address, active}`. The active level
is REQUIRED (D60): an NC switch reads 0 when a part is present, so a guessed
level inverts present and absent. What is stored is "actuated" (1/0). A
switching point may not be the production counter (D61).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iaiops.connectors.modbus.points import parse_point, read_point_value, read_ref_value
from iaiops.core.runtime.sensor import parse_profile

pytestmark = pytest.mark.unit


# ── grammar ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ref", "table", "address", "active"),
    [
        ("di:0:high", "discrete", 0, "high"),
        ("DI:12:low", "discrete", 12, "low"),
        ("co:3:high", "coil", 3, "high"),
    ],
)
def test_switching_points_parse(ref, table, address, active):
    point = parse_point(ref)
    assert (point.table, point.address, point.active) == (table, address, active)
    assert not point.legacy


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ("di:0", "active"),  # no default level (D60)
        ("di:0:on", "active"),
        ("di:0:high*2", "scale"),  # a bit has no scale
        ("di:0:uint16:high", "grammar"),  # nor a type
        ("co:x:high", "address"),
    ],
)
def test_switching_points_refuse_without_a_level_or_with_register_options(ref, message):
    with pytest.raises(ValueError, match=message):
        parse_point(ref)


# ── decoding: stored value is "actuated" ────────────────────────────────────


def _bits(*values):
    calls = []

    def read(table, address, count):
        calls.append((table, address, count))
        return list(values)[:count]

    read.calls = calls
    return read


@pytest.mark.parametrize(
    ("ref", "level", "actuated"),
    [
        ("di:5:high", 1, 1),
        ("di:5:high", 0, 0),
        ("di:5:low", 0, 1),  # NC switch: 0 = actuated
        ("di:5:low", 1, 0),
    ],
)
def test_actuated_follows_the_declared_level(ref, level, actuated):
    read = _bits(level)
    assert read_point_value(read, ref) == actuated
    assert read.calls == [("discrete", 5, 1)]


def test_an_empty_bit_answer_is_not_a_reading():
    from iaiops.core.runtime.sensor import InvalidReadingError

    with pytest.raises(InvalidReadingError):
        read_point_value(_bits(), "di:5:high")


# ── profiles ────────────────────────────────────────────────────────────────


def _profile(layout, **extra):
    return {
        "id": "presence",
        "protocol": "modbus",
        "source": "manual",
        "verified": "待核实",
        "channels": [{"name": "part", "layout": layout, "signal": "event", **extra}],
    }


def test_a_switching_channel_needs_its_active_level():
    with pytest.raises(ValueError, match="active"):
        parse_profile(_profile({"table": "discrete", "address": 0}))


def test_a_switching_channel_cannot_be_a_counter_or_a_waveform():
    with pytest.raises(ValueError, match="signal"):
        parse_profile(
            _profile({"table": "discrete", "address": 0, "active": "high"}, signal="counter")
        )


def test_a_switching_channel_has_no_register_options():
    with pytest.raises(ValueError, match="type|order|scale"):
        parse_profile(
            _profile({"table": "discrete", "address": 0, "active": "high", "type": "uint16"})
        )


def test_a_switching_channel_reads_through_ch_refs():
    profile = parse_profile(_profile({"table": "coil", "address": 7, "active": "low"}))
    read = _bits(0)
    assert read_ref_value(read, "ch:part", profile) == 1
    assert read.calls == [("coil", 7, 1)]


def test_profile_summary_shows_the_switching_layout():
    from iaiops.core.runtime.sensor import profile_summary

    summary = profile_summary(
        parse_profile(_profile({"table": "discrete", "address": 2, "active": "low"}))
    )
    assert summary["channels"][0]["layout"] == "discrete[2] active-low"


# ── every Modbus read path ──────────────────────────────────────────────────


class _Resp:
    def __init__(self, bits):
        self.bits = bits

    def isError(self):  # noqa: N802
        return False


class _Client:
    iaiops_unit_id = 1
    iaiops_sensor_profile = None

    def __init__(self, bits):
        self.bits = bits
        self.calls = []

    def read_discrete_inputs(self, address, count, device_id):
        self.calls.append(("discrete", address, count))
        return _Resp(self.bits[:count])

    def read_coils(self, address, count, device_id):
        self.calls.append(("coil", address, count))
        return _Resp(self.bits[:count])


def test_session_read_decodes_a_switching_point():
    from iaiops.core.runtime.capabilities import _session_read_modbus

    client = _Client([False])
    value, _ = _session_read_modbus(client, "di:4:low")
    assert value == 1 and client.calls == [("discrete", 4, 1)]


def test_one_shot_read_decodes_a_switching_point(monkeypatch):
    import iaiops.connectors.modbus.ops as ops
    from iaiops.core.runtime.capabilities import _monitor_modbus

    monkeypatch.setattr(ops, "modbus_read_coils", lambda t, address, count=1: {"bits": [True]})
    value, _ = _monitor_modbus(SimpleNamespace(sensor_profile=""), "co:9:high")
    assert value == 1


def test_health_summary_evaluates_a_switching_point(monkeypatch):
    import iaiops.core.runtime.connection as conn
    from iaiops.connectors.modbus import ops
    from iaiops.core.runtime.config import MonitorTag, TargetConfig

    class _Session(_Client):
        def connect(self):
            return True

        def close(self):
            return None

    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _Session([True]))
    target = TargetConfig(
        name="p", protocol="modbus", host="h", tags=(MonitorTag(ref="di:0:high", alarm_high=1),)
    )
    out = ops.modbus_health_summary(target)
    assert out["results"][0]["value"] == 1.0 and out["overall"] == "alarm"


# ── readiness: a switching point is not a production counter (D61) ──────────


def test_readiness_refuses_a_switching_point_as_the_counter(tmp_path):
    from iaiops.core.readiness.assess import assess
    from iaiops.core.runtime.config import AppConfig, MonitorTag, TargetConfig

    config = AppConfig(
        targets=(
            TargetConfig(
                name="line1",
                protocol="modbus",
                host="h",
                tags=(
                    MonitorTag(ref="hr:1:uint16", role="run_state", running_when=1),
                    MonitorTag(ref="di:0:high", role="total_count"),
                ),
                ideal_cycle_time_s=2.0,
            ),
        )
    )
    report = assess(config, db_path=tmp_path / "none.db")
    oee = next(c for c in report.capabilities if c.key == "oee")
    req = next(r for r in oee.requirements if r.key == "count_source")
    assert not req.met and "line1:di:0:high" in req.detail and "counter" in req.fix
