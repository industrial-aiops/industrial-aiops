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
            "verified": "待核实",
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


# ── review fixes (#257): the unit comes from the profile that decoded the value ──

PROFILE_TEXT = """id: force
protocol: modbus
source: manual
verified: 待核实
channels:
  - name: fz
    layout: {{table: input, address: 0, type: int16}}
    unit: {unit}
    scale: {scale}
    signal: level
"""


def _write_profile(path, unit, scale):
    import os

    path.write_text(PROFILE_TEXT.format(unit=unit, scale=scale), "utf-8")
    # A distinct mtime even within one clock tick: the cache keys on (mtime, size).
    stamp = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


def _decoding_reader(path, edits):
    """Reads through the REAL profile path (scale from the file), and applies
    ``edits[i]`` to the file before the i-th read when present."""
    from iaiops.connectors.modbus.points import profile_channel
    from iaiops.core.runtime.sensor.binding import endpoint_profile

    calls = {"n": 0}

    def read(target, ref):
        edit = edits.get(calls["n"])
        calls["n"] += 1
        if edit:
            _write_profile(path, *edit)
        return 1500 * profile_channel(ref, endpoint_profile(target)).scale, ""

    return read


def test_a_profile_edited_mid_run_never_pairs_a_value_with_a_stale_unit(tmp_path):
    """Review of #257: units were resolved once per run while values decoded
    with the file as it is now — 1.5 kN stored as "1.5 N", off by 1000×."""
    path = tmp_path / "force.yaml"
    _write_profile(path, "N", 1)
    target = SimpleNamespace(
        name="cell", protocol="modbus", sensor_profile=str(path), port_profiles=()
    )
    db = tmp_path / "s.db"
    run_collection(
        CollectionPlan(endpoint="cell", tags=("ch:fz",), duration_s=3, interval_ms=1000),
        target=target,
        reader=_decoding_reader(path, {1: ("kN", 0.001)}),
        db_path=db,
        clock=_Clock(),
    )
    rows = [(row["value"], row["unit"]) for row in query_samples(SampleFilter(), db)]
    assert rows[0] == (1500.0, "N")
    assert all(unit == "kN" for value, unit in rows[1:] if value == pytest.approx(1.5))
    assert ("1.5", "N") not in [(str(v), u) for v, u in rows]


def test_a_profile_edited_during_a_read_is_a_gap_not_a_guess(tmp_path):
    """Unit checked before AND after the read; if they differ the sample is not stored."""
    path = tmp_path / "force.yaml"
    _write_profile(path, "N", 1)
    target = SimpleNamespace(
        name="cell", protocol="modbus", sensor_profile=str(path), port_profiles=()
    )
    db = tmp_path / "s.db"
    result = run_collection(
        CollectionPlan(endpoint="cell", tags=("ch:fz",), duration_s=1, interval_ms=1000),
        target=target,
        reader=_decoding_reader(path, {0: ("kN", 0.001)}),  # edited inside the read
        db_path=db,
        clock=_Clock(),
    )
    assert result.samples_written == 0
    assert any("profile" in g["reason"] and "changed" in g["reason"] for g in result.gaps)


def test_unit_for_never_raises(monkeypatch):
    def explode(path):
        raise RecursionError("pathological yaml")

    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", explode)
    assert unit_for(_modbus_target(), "ch:fz") == ""


def test_a_unit_longer_than_the_store_keeps_is_refused_at_load():
    with pytest.raises(ValueError, match="unit"):
        _modbus_profile(unit="mm (target distance, 0.1 mm resolution)")
