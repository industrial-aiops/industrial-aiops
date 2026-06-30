"""DNP3 ops tests against a MOCKED master adapter.

opendnp3 is callback-based and unverified here, so ``_build_dnp3_client`` is
monkeypatched to return a fake adapter exposing the uniform interface
(enable/is_online/integrity_poll/shutdown) the ops rely on — exercising link
status and the integrity-poll grouping without a live outstation. Also covers the
driver's group→type mapping.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.dnp3 import ops
from iaiops.connectors.dnp3.driver import measurement_type
from iaiops.core.runtime.config import TargetConfig


class _FakeAdapter:
    def __init__(self, points, online=True):
        self._points = points
        self._online = online
        self.enabled = False
        self.shut = False

    def enable(self):
        self.enabled = True

    def is_online(self):
        return self._online

    def integrity_poll(self):
        return list(self._points)

    def shutdown(self):
        self.shut = True


@pytest.fixture
def outstation(monkeypatch):
    points = [
        {"group": 1, "type": "binary_input", "index": 0, "value": True,
         "quality": "ONLINE", "timestamp": ""},
        {"group": 30, "type": "analog_input", "index": 0, "value": 120.5,
         "quality": "ONLINE", "timestamp": ""},
        {"group": 30, "type": "analog_input", "index": 1, "value": 60.0,
         "quality": "ONLINE", "timestamp": ""},
        {"group": 20, "type": "counter", "index": 0, "value": 9000,
         "quality": "ONLINE", "timestamp": ""},
    ]
    adapter = _FakeAdapter(points)
    monkeypatch.setattr(conn, "_build_dnp3_client", lambda target: adapter)
    target = TargetConfig(name="rtu2", protocol="dnp3", host="10.0.0.6",
                          unit_id=4, master_address=1)
    return target, adapter


@pytest.mark.unit
def test_link_status(outstation):
    target, _ = outstation
    out = ops.dnp3_link_status(target)
    assert out["online"] is True
    assert out["outstation_address"] == 4
    assert out["master_address"] == 1


@pytest.mark.unit
def test_integrity_poll_groups_by_type(outstation):
    target, _ = outstation
    out = ops.dnp3_integrity_poll(target)
    assert out["point_count"] == 4
    assert out["by_type"]["analog_input"] == 2
    assert out["by_type"]["binary_input"] == 1
    assert out["by_type"]["counter"] == 1
    analog = [p for p in out["points"] if p["type"] == "analog_input"]
    assert analog[0]["value"] == 120.5


@pytest.mark.unit
def test_offline_outstation_raises(monkeypatch):
    adapter = _FakeAdapter([], online=False)
    monkeypatch.setattr(conn, "_build_dnp3_client", lambda target: adapter)
    monkeypatch.setattr(conn, "_wait_until", lambda pred, t, poll_s=0.05: bool(pred()))
    target = TargetConfig(name="rtu2", protocol="dnp3", host="10.0.0.6")
    with pytest.raises(conn.OTConnectionError, match="did not come online"):
        ops.dnp3_link_status(target)


@pytest.mark.unit
def test_shutdown_called(outstation):
    target, adapter = outstation
    ops.dnp3_integrity_poll(target)
    assert adapter.shut is True


@pytest.mark.unit
def test_measurement_type_mapping():
    assert measurement_type(1) == "binary_input"
    assert measurement_type(30) == "analog_input"
    assert measurement_type(20) == "counter"
    assert measurement_type(999).startswith("group_")


@pytest.mark.unit
def test_wrong_protocol_guarded():
    target = TargetConfig(name="x", protocol="modbus", host="1.2.3.4")
    with pytest.raises(conn.OTConnectionError, match="not dnp3"):
        with conn.dnp3_session(target):
            pass
