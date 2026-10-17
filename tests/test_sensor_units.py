"""E1 (HLD §17.5, D56): the unit travels with the value into the store.

Found on the lab LAN run of #249: the profile knew mm and N, the store's `unit`
column stayed empty. A unit is a property of the point's profile channel, so it
is resolved once per ref when a run starts. No profile → no unit, never a guess;
a profile unit still marked 待核实 (an unmapped IODD unit code) is not a unit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.runner import run_collection
from iaiops.core.runtime.sensor import parse_profile
from iaiops.core.runtime.sensor.binding import unit_for
from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

pytestmark = pytest.mark.unit


def _modbus_profile(unit="N"):
    return parse_profile(
        {
            "id": "force",
            "protocol": "modbus",
            "source": "manual",
            "verified": "bench",
            "channels": [
                {
                    "name": "fz",
                    "layout": {"table": "input", "address": 0, "type": "int16"},
                    "unit": unit,
                    "signal": "level",
                }
            ],
        }
    )


def _iolink_profile(unit="mm"):
    return parse_profile(
        {
            "id": "tof",
            "protocol": "iolink",
            "source": "iodd",
            "verified": "待核实",
            "channels": [
                {
                    "name": "distance",
                    "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                    "unit": unit,
                    "signal": "level",
                }
            ],
        }
    )


def _modbus_target():
    return SimpleNamespace(
        name="cell", protocol="modbus", sensor_profile="force.yaml", port_profiles=()
    )


def _iolink_target():
    return SimpleNamespace(
        name="m", protocol="iolink", sensor_profile="", port_profiles=((2, "tof.yaml"),)
    )


@pytest.fixture
def profiles(monkeypatch):
    table = {"force.yaml": _modbus_profile(), "tof.yaml": _iolink_profile()}
    monkeypatch.setattr(
        "iaiops.core.runtime.sensor.binding.cached_profile", lambda path: table[path]
    )
    return table


def test_profile_channels_have_their_unit(profiles):
    assert unit_for(_modbus_target(), "ch:fz") == "N"
    assert unit_for(_iolink_target(), "port2/distance") == "mm"


@pytest.mark.parametrize(
    ("target", "ref"),
    [
        (_modbus_target(), "40"),  # bare address: no profile behind it
        (_modbus_target(), "ir:0:float32:CDAB"),  # typed point: type, not unit
        (_modbus_target(), "ch:nope"),  # unknown channel
        (_modbus_target(), "ab:fz"),  # not a channel ref, even if its tail names one
        (_iolink_target(), "port3/distance"),  # unprofiled port
        (SimpleNamespace(name="u", protocol="opcua"), "ns=2;s=x"),  # not judged here
    ],
)
def test_no_profile_channel_means_no_unit(profiles, target, ref):
    assert unit_for(target, ref) == ""


def test_an_unconfirmed_unit_is_not_stored(monkeypatch):
    monkeypatch.setattr(
        "iaiops.core.runtime.sensor.binding.cached_profile",
        lambda path: _iolink_profile(unit="unitCode 1013 (待核实)"),
    )
    assert unit_for(_iolink_target(), "port2/distance") == ""


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds if seconds > 0 else 1.0


def test_collected_samples_carry_the_unit_into_the_store(profiles, tmp_path):
    db = tmp_path / "s.db"
    run_collection(
        CollectionPlan(endpoint="cell", tags=("ch:fz", "40"), duration_s=3, interval_ms=1000),
        target=_modbus_target(),
        reader=lambda target, ref: (12.5, ""),
        db_path=db,
        clock=_Clock(),
    )
    units = {row["tag"]: row["unit"] for row in query_samples(SampleFilter(), db)}
    assert units == {"ch:fz": "N", "40": ""}


def test_a_profile_that_cannot_be_read_leaves_the_unit_empty_and_the_run_going(
    monkeypatch, tmp_path
):
    def broken(path):
        raise OSError("gone")

    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", broken)
    db = tmp_path / "s.db"
    result = run_collection(
        CollectionPlan(endpoint="cell", tags=("ch:fz",), duration_s=2, interval_ms=1000),
        target=_modbus_target(),
        reader=lambda target, ref: (1.0, ""),
        db_path=db,
        clock=_Clock(),
    )
    assert result.samples_written == 2
    assert {row["unit"] for row in query_samples(SampleFilter(), db)} == {""}
