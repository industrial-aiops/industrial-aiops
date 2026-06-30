"""PROFINET-DCP ops tests against a MOCKED pnio-dcp DCP.

PROFINET-DCP is a layer-2 protocol needing raw-socket access on the NIC on the
PROFINET subnet, so the pnio-dcp ``DCP`` is faked by monkeypatching
``connection._build_profinet_dcp`` — exercising IdentifyAll discovery, identify by
name, targeted Get by MAC, role-bitmask decoding, and the asset register WITHOUT
any hardware.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.profinet import ops
from iaiops.core.runtime.config import TargetConfig


class _FakeDevice:
    def __init__(self, name, mac, ip, netmask="255.255.255.0", gateway="0.0.0.0",
                 vendor_id=0x002A, device_id=0x0301, device_role=0x02, family="S7-1500"):
        self.name_of_station = name
        self.MAC = mac
        self.IP = ip
        self.netmask = netmask
        self.gateway = gateway
        self.vendor_id = vendor_id
        self.device_id = device_id
        self.device_role = device_role
        self.family = family


class _FakeDCP:
    def __init__(self, devices, with_get=False):
        self._devices = devices
        self.closed = False
        if with_get:
            self.get_name_of_station = lambda mac: self._by_mac(mac).name_of_station
            self.get_ip_address = lambda mac: self._by_mac(mac).IP

    def _by_mac(self, mac):
        for d in self._devices:
            if d.MAC.lower() == mac.lower():
                return d
        raise KeyError(mac)

    def identify_all(self):
        return list(self._devices)

    def close(self):
        self.closed = True


def _target():
    return TargetConfig(name="cell1", protocol="profinet", host="192.168.0.10")


@pytest.fixture
def pn(monkeypatch):
    devices = [
        _FakeDevice("plc1", "00:1b:1b:00:00:01", "192.168.0.20",
                    device_role=0x02, family="S7-1500"),       # io_controller
        _FakeDevice("et200sp-1", "00:1b:1b:00:00:02", "192.168.0.21",
                    device_role=0x01, family="ET200SP"),       # io_device
    ]
    dcp = _FakeDCP(devices)
    monkeypatch.setattr(conn, "_build_profinet_dcp", lambda target: dcp)
    return dcp


# ─── discovery ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_discover_lists_all_stations(pn):
    out = ops.profinet_discover(_target())
    assert out["station_count"] == 2
    names = [st["name_of_station"] for st in out["stations"]]
    assert names == ["plc1", "et200sp-1"]
    first = out["stations"][0]
    assert first["mac"] == "00:1b:1b:00:00:01"
    assert first["ip"] == "192.168.0.20"
    assert first["vendor_id"] == 0x002A
    assert "io_controller" in first["device_roles"]


@pytest.mark.unit
def test_discover_closes_handle(pn):
    ops.profinet_discover(_target())
    assert pn.closed is True


# ─── identify by name ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_identify_station_found_case_insensitive(pn):
    out = ops.profinet_identify_station(_target(), "PLC1")
    assert out["found"] is True
    assert out["name_of_station"] == "plc1"
    assert out["ip"] == "192.168.0.20"
    assert out["device_family"] == "S7-1500"


@pytest.mark.unit
def test_identify_station_not_found(pn):
    out = ops.profinet_identify_station(_target(), "ghost")
    assert out["found"] is False
    assert "note" in out


@pytest.mark.unit
def test_identify_station_requires_name(pn):
    assert "error" in ops.profinet_identify_station(_target(), "")


# ─── params by MAC ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_station_params_via_identify_fallback(pn):
    # _FakeDCP has no get_* helpers → falls back to IdentifyAll filter by MAC.
    out = ops.profinet_station_params(_target(), "00:1b:1b:00:00:02")
    assert out["found"] is True
    assert out["name_of_station"] == "et200sp-1"


@pytest.mark.unit
def test_station_params_via_unicast_get(monkeypatch):
    devices = [_FakeDevice("plc1", "00:1b:1b:00:00:01", "192.168.0.20")]
    dcp = _FakeDCP(devices, with_get=True)
    monkeypatch.setattr(conn, "_build_profinet_dcp", lambda target: dcp)
    out = ops.profinet_station_params(_target(), "00:1b:1b:00:00:01")
    assert out["found"] is True
    assert out["name_of_station"] == "plc1"
    assert out["ip"] == "192.168.0.20"


@pytest.mark.unit
def test_station_params_requires_mac(pn):
    assert "error" in ops.profinet_station_params(_target(), "")


# ─── asset inventory ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_asset_inventory_counts_roles(pn):
    out = ops.profinet_asset_inventory(_target())
    assert out["asset_count"] == 2
    assert out["io_controller_count"] == 1
    assert out["io_device_count"] == 1
    assert out["method"] == "dcp_identify_all"
    plc = next(a for a in out["assets"] if a["name_of_station"] == "plc1")
    assert plc["roles"] == ["io_controller"]


# ─── error surface ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_wrong_protocol_is_teaching_error(monkeypatch):
    # profinet_dcp guards the protocol before building anything.
    target = TargetConfig(name="x", protocol="modbus", host="10.0.0.1")
    with pytest.raises(conn.OTConnectionError, match="not profinet"):
        with conn.profinet_dcp(target):
            pass


@pytest.mark.unit
def test_construction_permission_error_is_translated(monkeypatch):
    # DCP(ip) binds a raw socket in its constructor; a PermissionError there must
    # be routed through the teaching translator, not raised raw.
    def boom(target):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(conn, "_build_profinet_dcp", boom)
    target = TargetConfig(name="cell1", protocol="profinet", host="192.168.0.10")
    with pytest.raises(conn.OTConnectionError, match="raw-socket permission"):
        ops.profinet_discover(target)


@pytest.mark.unit
def test_role_bitmask_decodes_multidevice(monkeypatch):
    dev = _FakeDevice("combo", "00:1b:1b:00:00:09", "192.168.0.30", device_role=0x03)
    dcp = _FakeDCP([dev])
    monkeypatch.setattr(conn, "_build_profinet_dcp", lambda target: dcp)
    out = ops.profinet_discover(_target())
    roles = out["stations"][0]["device_roles"]
    assert "io_device" in roles and "io_controller" in roles
