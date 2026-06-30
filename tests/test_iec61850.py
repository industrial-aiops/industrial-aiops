"""IEC 61850 MMS ops tests against a MOCKED libiec61850 adapter.

The libiec61850 binding is unverified here, so ``_build_iec61850_client`` is
monkeypatched to return a fake adapter exposing the uniform interface
(connect/close/get_logical_devices/get_data_directory/read) — exercising the
device directory, browse, and attribute read without a live IED.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.iec61850 import ops
from iaiops.core.runtime.config import TargetConfig


class _FakeAdapter:
    def __init__(self):
        self.connected = False
        self.closed = False
        self._model = {
            "": ["IED1LD0", "IED1MEAS"],
            "IED1LD0": ["LLN0", "MMXU1"],
            "IED1MEAS": ["MMXU1"],
        }
        self._values = {("IED1MMXU1.TotW.mag.f", "MX"): 1234.5}

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True

    def get_logical_devices(self):
        return self._model[""]

    def get_data_directory(self, reference):
        return self._model.get(reference, [])

    def read(self, reference, fc):
        if (reference, fc) in self._values:
            return {"reference": reference, "fc": fc, "value": self._values[(reference, fc)]}
        return {"reference": reference, "fc": fc, "error": "no such object"}


@pytest.fixture
def ied(monkeypatch):
    adapter = _FakeAdapter()
    monkeypatch.setattr(conn, "_build_iec61850_client", lambda target: adapter)
    return TargetConfig(name="ied1", protocol="iec61850", host="10.0.0.7"), adapter


@pytest.mark.unit
def test_device_directory(ied):
    target, _ = ied
    out = ops.iec61850_device_directory(target)
    assert out["logical_device_count"] == 2
    assert out["logical_devices"][0]["logical_device"] == "IED1LD0"


@pytest.mark.unit
def test_device_directory_with_children(ied):
    target, _ = ied
    out = ops.iec61850_device_directory(target, include_children=True)
    ld0 = next(d for d in out["logical_devices"] if d["logical_device"] == "IED1LD0")
    assert ld0["child_count"] == 2
    assert "MMXU1" in ld0["children"]


@pytest.mark.unit
def test_browse(ied):
    target, _ = ied
    out = ops.iec61850_browse(target, "IED1LD0")
    assert out["child_count"] == 2
    assert "LLN0" in out["children"]


@pytest.mark.unit
def test_browse_requires_reference(ied):
    target, _ = ied
    assert "error" in ops.iec61850_browse(target, "")


@pytest.mark.unit
def test_read_value(ied):
    target, _ = ied
    out = ops.iec61850_read(target, "IED1MMXU1.TotW.mag.f", "MX")
    assert out["value"] == 1234.5
    assert out["fc"] == "MX"
    assert out["error"] == ""


@pytest.mark.unit
def test_read_missing_object_reports_error(ied):
    target, _ = ied
    out = ops.iec61850_read(target, "IED1.Nope", "MX")
    assert out["error"]


@pytest.mark.unit
def test_close_called(ied):
    target, adapter = ied
    ops.iec61850_device_directory(target)
    assert adapter.closed is True


@pytest.mark.unit
def test_wrong_protocol_guarded():
    target = TargetConfig(name="x", protocol="modbus", host="1.2.3.4")
    with pytest.raises(conn.OTConnectionError, match="not iec61850"):
        with conn.iec61850_session(target):
            pass
