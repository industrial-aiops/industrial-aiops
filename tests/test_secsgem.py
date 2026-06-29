"""SECS/GEM connector — host-side reads against an in-process fake handler."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iaiops.connectors.secsgem import ops
from iaiops.core.runtime import connection
from iaiops.core.runtime.connection import OTConnectionError


def _target(host="127.0.0.1", protocol="secsgem"):
    return SimpleNamespace(name="eqp1", protocol=protocol, host=host, port=5000, unit_id=0)


class _SF:
    """Mimics a secsgem SecsStreamFunction: undecoded until no-arg .get() is called."""

    def __init__(self, data):
        self._data = data

    def get(self):
        return self._data


class _FakeHostHandler:
    def __init__(self, communicating=True):
        self._communicating = communicating
        self.enabled = False
        self.disabled = False
        self.communication_state = SimpleNamespace(current="COMMUNICATING")

    def enable(self):
        self.enabled = True

    def disable(self):
        self.disabled = True

    def waitfor_communicating(self, timeout=None):
        return self._communicating

    def are_you_there(self):
        return {"MDLN": "CSOT-T7", "SOFTREV": "1.2.3"}

    # SV/EC calls return an undecoded SecsStreamFunction (needs .get()) — matches the
    # real lib, so a missing _decoded() in ops would surface here as stringified junk.
    def list_svs(self):
        return _SF([{"svid": 1, "name": "Clock"}, {"svid": 2, "name": "Temp"}])

    def request_svs(self, svs):
        return _SF([{"svid": i, "value": 100 + i} for i in svs])

    def list_ecs(self):
        return _SF([{"ecid": 10, "name": "SetPoint", "min": 0, "max": 500}])

    def request_ecs(self, ecs):
        return _SF([{"ecid": i, "value": 250} for i in ecs])

    # alarms / process-program list already .get() internally → plain lists.
    def list_alarms(self):
        return [{"alid": 7, "alcd": 132, "text": "Chamber over temp"}]

    def get_process_program_list(self):
        return ["RECIPE_A", "RECIPE_B"]


@pytest.fixture
def fake(monkeypatch):
    handler = _FakeHostHandler()
    monkeypatch.setattr(connection, "_build_secsgem_host", lambda t: handler)
    return handler


def test_equipment_status(fake):
    r = ops.equipment_status(_target())
    assert r["communication_state"] == "COMMUNICATING"
    assert r["are_you_there"]["MDLN"] == "CSOT-T7"
    assert fake.enabled and fake.disabled  # session enables then always disables


def test_list_and_read_status_variables(fake):
    assert ops.list_status_variables(_target())["count"] == 2
    r = ops.read_status_variables(_target(), [1, 2])
    assert r["values"] == [{"svid": 1, "value": 101}, {"svid": 2, "value": 102}]


def test_list_and_read_equipment_constants(fake):
    assert ops.list_equipment_constants(_target())["count"] == 1
    assert ops.read_equipment_constants(_target(), [10])["values"][0]["value"] == 250


def test_alarms_and_process_programs(fake):
    assert ops.list_alarms(_target())["alarms"][0]["alid"] == 7
    assert ops.list_process_programs(_target())["process_programs"] == ["RECIPE_A", "RECIPE_B"]


def test_empty_id_lists_error_without_connecting(fake):
    assert "error" in ops.read_status_variables(_target(), [])
    assert "error" in ops.read_equipment_constants(_target(), [])


def test_not_communicating_raises_teaching_error(monkeypatch):
    handler = _FakeHostHandler(communicating=False)
    monkeypatch.setattr(connection, "_build_secsgem_host", lambda t: handler)
    with pytest.raises(OTConnectionError) as ei:
        ops.equipment_status(_target())
    assert "communicating" in str(ei.value).lower()
    assert handler.disabled  # still cleaned up


def test_missing_host_validation():
    with pytest.raises(OTConnectionError) as ei:
        ops.equipment_status(_target(host=""))
    assert "host" in str(ei.value).lower()


def test_wrong_protocol_validation():
    with pytest.raises(OTConnectionError):
        ops.equipment_status(_target(protocol="opcua"))
