"""#249 follow-ups 3 and 5, verified on the path `collect run` actually takes.

The 0.30.0 audit found a 1000× unit error the suite missed because the tests
drove a stand-in reader, not the session the collector uses. These tests wire
the run exactly as ``iaiops collect run`` does (``session_read_for`` +
``session_builder_for`` for Modbus, ``read_point`` for IO-Link, which has no
held session) over fake transports, with real profile files on disk:

* units: the store's ``unit`` column is filled for Modbus ``ch:`` and IO-Link
  port channels, and empty for a point with no profile behind it;
* cached vs reloaded: every read path — collection session, monitor, one-shot,
  the health summary — decodes with the profile file as it is NOW, so an edit
  never pairs a value with another profile's unit or scale.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

from iaiops.connectors.iolink import client as iolink_client
from iaiops.connectors.iolink import points as iolink_points
from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.reader import read_point, session_builder_for, session_read_for
from iaiops.core.collect.runner import run_collection
from iaiops.core.runtime import capabilities as caps
from iaiops.core.runtime import connection as conn
from iaiops.core.runtime.config import MonitorTag, TargetConfig
from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

pytestmark = pytest.mark.unit

MODBUS_PROFILE = """id: force
protocol: modbus
source: manual
verified: 待核实
channels:
  - name: fz
    layout: {{table: input, address: 4, type: uint16}}
    unit: {unit}
    scale: {scale}
    signal: level
"""

IOLINK_PROFILE = """id: tof
protocol: iolink
source: iodd
verified: 待核实
pd_bits: 32
channels:
  - name: distance
    layout: {{bit_offset: 16, bit_length: 16, type: uint}}
    unit: {unit}
    scale: {scale}
    signal: level
"""


def _write(path, template: str, unit: str, scale: float) -> None:
    path.write_text(template.format(unit=unit, scale=scale), "utf-8")
    # A distinct mtime even inside one clock tick: the profile cache keys on it.
    stamp = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds if seconds > 0 else 1.0


class _Resp:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):  # noqa: N802 — pymodbus API
        return False


class _ModbusDevice:
    """Input 4 = 1500 raw; holding 40 = 7. Counts connections."""

    opened = 0

    def connect(self):
        type(self).opened += 1
        return True

    def close(self):
        return None

    def read_input_registers(self, address, *, count=1, device_id=1, **kw):
        return _Resp(([0] * 4 + [1500])[address : address + count])

    def read_holding_registers(self, address, *, count=1, device_id=1, **kw):
        return _Resp([7] * count)


@pytest.fixture
def modbus(monkeypatch, tmp_path):
    _ModbusDevice.opened = 0
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _ModbusDevice())
    path = tmp_path / "force.yaml"
    _write(path, MODBUS_PROFILE, "N", 1)
    target = TargetConfig(
        name="cell", protocol="modbus", host="127.0.0.1", unit_id=1, sensor_profile=str(path)
    )
    return target, path


def _edit_before_read(reader, path, template, at: int, unit: str, scale: float):
    """The real reader, with the profile file edited just before read ``at``."""
    calls = {"n": 0}

    def read(subject, ref):
        if calls["n"] == at:
            _write(path, template, unit, scale)
        calls["n"] += 1
        return reader(subject, ref)

    return read


def _rows(db):
    return [(r["tag"], r["value"], r["unit"]) for r in query_samples(SampleFilter(), db)]


def test_modbus_collect_run_stores_the_unit_through_the_session(modbus, tmp_path):
    target, _ = modbus
    db = tmp_path / "s.db"
    reader = session_read_for("modbus")
    assert reader is caps._session_read_modbus  # the path `collect run` takes
    result = run_collection(
        CollectionPlan(endpoint="cell", tags=("ch:fz", "40"), duration_s=2, interval_ms=1000),
        target=target,
        reader=reader,
        session_builder=session_builder_for("modbus"),
        db_path=db,
        clock=_Clock(),
    )
    assert _ModbusDevice.opened == 1  # one held session, not a connect per read
    assert result.samples_written == 4
    assert {(tag, unit) for tag, _, unit in _rows(db)} == {("ch:fz", "N"), ("40", "")}
    assert {value for tag, value, _ in _rows(db) if tag == "ch:fz"} == {1500.0}


def test_modbus_session_edit_mid_run_keeps_value_and_unit_together(modbus, tmp_path):
    target, path = modbus
    db = tmp_path / "s.db"
    run_collection(
        CollectionPlan(endpoint="cell", tags=("ch:fz",), duration_s=3, interval_ms=1000),
        target=target,
        reader=_edit_before_read(
            session_read_for("modbus"), path, MODBUS_PROFILE, at=1, unit="kN", scale=0.001
        ),
        session_builder=session_builder_for("modbus"),
        db_path=db,
        clock=_Clock(),
    )
    # The edit lands between the runner's "unit before" and the read, so that
    # tick is a gap; every stored row pairs a value with its own profile's unit.
    rows = [(value, unit) for _, value, unit in _rows(db)]
    assert rows[0] == (1500.0, "N")
    assert rows[1:] and all(row == (pytest.approx(1.5), "kN") for row in rows[1:])
    assert (1500.0, "kN") not in rows


# ── IO-Link: no held session; `collect run` reads through `read_point` ──

PDIN = "/iolinkmaster/port[2]/iolinkdevice/pdin/getdata"


@pytest.fixture
def iolink(monkeypatch, tmp_path):
    def post(url, payload, timeout):
        if payload["adr"] == PDIN:
            return json.dumps({"cid": 1, "code": 200, "data": {"value": "0BB80000"}})
        return json.dumps({"cid": 1, "code": 503})

    monkeypatch.setattr(iolink_client, "_http_post", post)
    iolink_points.clear_identity_cache()
    path = tmp_path / "tof.yaml"
    _write(path, IOLINK_PROFILE, "mm", 1)
    target = TargetConfig(
        name="m", protocol="iolink", agent_url="http://master", port_profiles=((2, str(path)),)
    )
    return target, path


def test_iolink_collect_run_stores_the_unit(iolink, tmp_path):
    target, _ = iolink
    assert session_read_for("iolink") is None  # so `collect run` uses read_point
    db = tmp_path / "s.db"
    result = run_collection(
        CollectionPlan(endpoint="m", tags=("port2/distance",), duration_s=2, interval_ms=1000),
        target=target,
        reader=read_point,
        db_path=db,
        clock=_Clock(),
    )
    assert result.samples_written == 2
    assert set(_rows(db)) == {("port2/distance", 3000.0, "mm")}


def test_iolink_edit_mid_run_keeps_value_and_unit_together(iolink, tmp_path):
    target, path = iolink
    db = tmp_path / "s.db"
    run_collection(
        CollectionPlan(endpoint="m", tags=("port2/distance",), duration_s=3, interval_ms=1000),
        target=target,
        reader=_edit_before_read(read_point, path, IOLINK_PROFILE, at=1, unit="m", scale=0.001),
        db_path=db,
        clock=_Clock(),
    )
    rows = [(value, unit) for _, value, unit in _rows(db)]
    assert rows[0] == (3000.0, "mm")
    assert rows[1:] and all(row == (pytest.approx(3.0), "m") for row in rows[1:])
    assert (3000.0, "m") not in rows


# ── Every other read path resolves the profile per read, too ──


def _modbus_paths(target):
    def monitor():
        return caps.REGISTRY["modbus"].monitor_read(target, "ch:fz")[0]

    def one_shot():
        return caps.REGISTRY["modbus"].read_ref(target, "ch:fz")["value"]

    def rca_tags():
        # RCA samples its tags through monitor._read_point (rca_collect) and its
        # dataflow verdict through read_ref (the one-shot case).
        from iaiops.core.brain.monitor import _read_point

        return _read_point(target, "ch:fz")[0]

    def health():
        from iaiops.connectors.modbus.ops import modbus_health_summary

        tagged = replace(target, tags=(MonitorTag(ref="ch:fz"),))
        return modbus_health_summary(tagged)["results"][0]["value"]

    return {
        "monitor": monitor,
        "one_shot": one_shot,
        "rca_tags": rca_tags,
        "health_summary": health,
    }


@pytest.mark.parametrize("path_name", ["monitor", "one_shot", "rca_tags", "health_summary"])
def test_modbus_read_paths_use_the_profile_as_it_is_now(modbus, monkeypatch, path_name):
    target, path = modbus
    # One-shot and monitor reads open their own connection per call.
    monkeypatch.setattr(
        caps,
        "_modbus_ops_reader",
        lambda t: lambda table, address, count: [1500] * count,
    )
    read = _modbus_paths(target)[path_name]
    assert read() == pytest.approx(1500.0)
    _write(path, MODBUS_PROFILE, "kN", 0.001)
    assert read() == pytest.approx(1.5)


@pytest.mark.parametrize("path_name", ["monitor", "one_shot"])
def test_iolink_read_paths_use_the_profile_as_it_is_now(iolink, path_name):
    target, path = iolink
    cap = caps.REGISTRY["iolink"]

    def read():
        if path_name == "monitor":
            return cap.monitor_read(target, "port2/distance")[0]
        return cap.read_ref(target, "port2/distance")["value"]

    assert read() == pytest.approx(3000.0)
    _write(path, IOLINK_PROFILE, "m", 0.001)
    assert read() == pytest.approx(3.0)
