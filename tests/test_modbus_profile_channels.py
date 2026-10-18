"""Modbus `ch:<name>` refs decode through the endpoint's sensor profile (S3)."""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from iaiops.core.runtime import capabilities as caps
from iaiops.core.runtime.sensor import parse_profile
from iaiops.core.runtime.session_factory import OTNoReadingError

pytestmark = pytest.mark.unit

PROFILE = parse_profile(
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


def _cdab(value: float) -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    return [(c << 8) | d, (a << 8) | b]


class _Resp:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):  # noqa: N802 — pymodbus API
        return False


class _Client:
    iaiops_unit_id = 1

    def __init__(self, words, profile):
        self.words = words
        self.calls = []
        self.iaiops_sensor_profile = profile

    def read_input_registers(self, address, count, device_id):
        self.calls.append(("input", address, count))
        return _Resp(self.words[:count])


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: PROFILE)
    return SimpleNamespace(name="cell", protocol="modbus", sensor_profile="force.yaml")


def test_session_read_decodes_a_profile_channel():
    client = _Client(_cdab(-120.5), PROFILE)
    value, _ = caps._session_read_modbus(client, "ch:fz")
    assert value == pytest.approx(-120.5)
    assert client.calls == [("input", 4, 2)]


def test_out_of_range_channel_value_is_a_gap():
    client = _Client(_cdab(999.0), PROFILE)
    with pytest.raises(OTNoReadingError, match="range"):
        caps._session_read_modbus(client, "ch:fz")


def test_channel_ref_without_a_profile_refuses():
    client = _Client(_cdab(1.0), None)
    with pytest.raises(ValueError, match="sensor_profile"):
        caps._session_read_modbus(client, "ch:fz")


def test_one_shot_read_uses_the_endpoint_profile(monkeypatch, bound):
    import iaiops.connectors.modbus.ops as ops

    monkeypatch.setattr(
        ops,
        "modbus_read_input",
        lambda t, address, count=1, decode="uint16": {"raw_registers": _cdab(12.0)[:count]},
    )
    value, _ = caps._monitor_modbus(bound, "ch:fz")
    assert value == pytest.approx(12.0)


def test_the_session_carries_the_profile(bound):
    from iaiops.core.runtime.connection import _prepare_modbus

    client = SimpleNamespace()
    _prepare_modbus(client, SimpleNamespace(unit_id=2, sensor_profile="force.yaml"))
    assert client.iaiops_sensor_profile is PROFILE


def test_plan_time_check_knows_the_channels(bound):
    from iaiops.core.collect.reader import ref_problems

    problems = ref_problems(bound, ("ch:fz", "ch:fx", "40"))
    assert len(problems) == 1 and "fz" in problems[0]
    unbound = SimpleNamespace(name="x", protocol="modbus", sensor_profile="")
    assert "sensor_profile" in ref_problems(unbound, ("ch:fz",))[0]


def _write_profile(path, unit: str, scale: float) -> None:
    import yaml

    path.write_text(
        yaml.safe_dump(
            {
                "id": "force",
                "protocol": "modbus",
                "source": "manual",
                "verified": "待核实",
                "channels": [
                    {
                        "name": "fz",
                        "layout": {"table": "input", "address": 4, "type": "uint16"},
                        "unit": unit,
                        "scale": scale,
                        "signal": "level",
                    }
                ],
            }
        )
    )


def test_session_decodes_with_the_profile_the_unit_comes_from(tmp_path):
    """The value and its unit must come from ONE profile (HLD §17.5, D56).

    The session used to decode with the profile it copied at open time while the
    runner took the unit from the file on every read — so editing the profile
    mid-run (N, scale 1 → kN, scale 0.001) stored raw 1500 as "1500 kN": a
    1000× error carrying a perfectly plausible unit.
    """
    import os

    from iaiops.core.runtime.connection import _prepare_modbus
    from iaiops.core.runtime.sensor.binding import unit_for

    path = tmp_path / "force.yaml"
    _write_profile(path, "N", 1.0)
    target = SimpleNamespace(name="cell", protocol="modbus", unit_id=1, sensor_profile=str(path))
    client = _Client([1500], None)
    _prepare_modbus(client, target)

    value, _ = caps._session_read_modbus(client, "ch:fz")
    assert (value, unit_for(target, "ch:fz")) == (pytest.approx(1500.0), "N")

    _write_profile(path, "kN", 0.001)
    st = path.stat()
    # A later edit within the same session.
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    value, _ = caps._session_read_modbus(client, "ch:fz")
    assert (value, unit_for(target, "ch:fz")) == (pytest.approx(1.5), "kN")
