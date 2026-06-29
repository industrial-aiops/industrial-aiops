"""Active asset-inventory tests with mocked protocol clients (no live devices).

Exercises the active-fingerprint aggregation: a reachable S7 PLC (mocked pyS7
client) yields an identity row; an unreachable Modbus device becomes a
``reachable: false`` row rather than raising.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.core.brain import asset_inventory as asset
from iaiops.core.runtime.config import TargetConfig


class _FakeS7Client:
    def __init__(self):
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def get_cpu_info(self):
        return {"ModuleName": "CPU 1511-1 PN", "SerialNumber": "S123", "Version": "2.8"}

    def get_cpu_status(self):
        return "run"


class _DeadModbusClient:
    def connect(self):
        return False  # never connects → OTConnectionError → reachable:false

    def close(self):
        pass


@pytest.mark.unit
def test_asset_inventory_mixed_reachability(monkeypatch):
    monkeypatch.setattr(conn, "_build_s7_client", lambda target: _FakeS7Client())
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: _DeadModbusClient())
    targets = [
        TargetConfig(name="press1", protocol="s7", host="10.0.0.1", rack=0, slot=1),
        TargetConfig(name="plc2", protocol="modbus", host="10.0.0.5"),
    ]
    out = asset.asset_inventory(targets)
    assert out["asset_count"] == 2
    assert out["reachable_count"] == 1
    assert out["unreachable_count"] == 1
    assert out["method"] == "active_fingerprint"

    by_ep = {a["endpoint"]: a for a in out["assets"]}
    s7 = by_ep["press1"]
    assert s7["reachable"] is True
    assert "Siemens" in s7["vendor"]
    assert s7["model"] == "CPU 1511-1 PN"
    assert s7["serial"] == "S123"
    assert s7["last_seen"]  # ISO timestamp recorded

    modbus = by_ep["plc2"]
    assert modbus["reachable"] is False
    assert modbus["error"]


@pytest.mark.unit
def test_asset_inventory_empty():
    out = asset.asset_inventory([])
    assert out["asset_count"] == 0
    assert out["reachable_count"] == 0
