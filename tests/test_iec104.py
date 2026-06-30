"""IEC 60870-5-104 ops tests against a MOCKED c104 client/connection.

The c104 binding is unverified against a live RTU, so ``_build_iec104_client`` is
monkeypatched to return a fake (client, connection) whose stations/points
duck-type the c104 surface — exercising connection info, general interrogation,
and single-point read without any RTU.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.iec104 import ops
from iaiops.core.runtime.config import TargetConfig


class _Point:
    def __init__(self, ioa, type_name, value, quality="GOOD", recorded_at="2026-06-29T10:00:00"):
        self.io_address = ioa
        self.type = type(type_name, (), {"name": type_name})()
        self.value = value
        self.quality = type(quality, (), {"name": quality})()
        self.recorded_at = recorded_at


class _Station:
    def __init__(self, ca, points):
        self.common_address = ca
        self.points = points


class _Conn:
    def __init__(self, stations, connected=True):
        self.stations = stations
        self.is_connected = connected


class _Client:
    def __init__(self, conn):
        self._conn = conn
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False


@pytest.fixture
def rtu(monkeypatch):
    station = _Station(1, [
        _Point(1001, "M_ME_NC_1", 50.0),
        _Point(1002, "M_SP_NA_1", 1),
    ])
    conn_obj = _Conn([station])
    client = _Client(conn_obj)
    monkeypatch.setattr(conn, "_build_iec104_client", lambda target: (client, conn_obj))
    return TargetConfig(name="rtu1", protocol="iec104", host="10.0.0.5", common_address=1)


@pytest.mark.unit
def test_connection_info(rtu):
    out = ops.iec104_connection_info(rtu)
    assert out["connected"] is True
    assert out["station_count"] == 1
    assert out["common_addresses"] == [1]
    assert out["configured_common_address"] == 1


@pytest.mark.unit
def test_interrogate_returns_points(rtu):
    out = ops.iec104_interrogate(rtu)
    assert out["common_address"] == 1
    assert out["point_count"] == 2
    p0 = out["points"][0]
    assert p0["io_address"] == 1001
    assert p0["type"] == "M_ME_NC_1"
    assert p0["value"] == 50.0
    assert p0["quality"] == "GOOD"


@pytest.mark.unit
def test_read_point_found(rtu):
    out = ops.iec104_read_point(rtu, 1002)
    assert out["found"] is True
    assert out["io_address"] == 1002
    assert out["value"] == 1


@pytest.mark.unit
def test_read_point_missing(rtu):
    out = ops.iec104_read_point(rtu, 9999)
    assert out["found"] is False


@pytest.mark.unit
def test_interrogate_unknown_ca_errors(rtu):
    out = ops.iec104_interrogate(rtu, common_address=77)
    assert "error" in out


@pytest.mark.unit
def test_wrong_protocol_guarded():
    target = TargetConfig(name="x", protocol="modbus", host="1.2.3.4")
    with pytest.raises(conn.OTConnectionError, match="not iec104"):
        with conn.iec104_session(target):
            pass


@pytest.mark.unit
def test_construction_error_is_translated(monkeypatch):
    # add_connection() I/O failure at build time must be translated, not raised raw.
    def boom(target):
        raise RuntimeError("c104 add_connection blew up")

    monkeypatch.setattr(conn, "_build_iec104_client", boom)
    target = TargetConfig(name="rtu1", protocol="iec104", host="10.0.0.5")
    with pytest.raises(conn.OTConnectionError, match="IEC104 operation"):
        ops.iec104_connection_info(target)


@pytest.mark.unit
def test_not_connected_raises(monkeypatch):
    conn_obj = _Conn([], connected=False)
    client = _Client(conn_obj)
    monkeypatch.setattr(conn, "_build_iec104_client", lambda target: (client, conn_obj))
    monkeypatch.setattr(conn, "_wait_until", lambda pred, t, poll_s=0.05: bool(pred()))
    target = TargetConfig(name="rtu1", protocol="iec104", host="10.0.0.5")
    with pytest.raises(conn.OTConnectionError, match="did not"):
        ops.iec104_connection_info(target)
