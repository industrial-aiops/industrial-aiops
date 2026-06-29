"""EtherNet/IP (pycomm3 Logix) ops tests against a mocked LogixDriver.

A real ControlLogix/CompactLogix controller is heavy to stand up, so the pycomm3
``LogixDriver`` is faked by monkeypatching ``connection._build_eip_client``. This
exercises the full session, tag discovery, read/batch-read, and write
dry-run/undo-capture paths.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.eip import ops
from iaiops.core.runtime.config import TargetConfig

# pycomm3's Tag is a 4-field namedtuple (tag, value, type, error).
Tag = namedtuple("Tag", "tag value type error")


class _FakeLogixDriver:
    """Minimal pycomm3 LogixDriver double backed by a tag→value dict."""

    def __init__(self, values=None):
        self._values = values or {}
        self.written: dict[str, object] = {}
        self.opened = False

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def get_plc_info(self):
        return {
            "vendor": "Rockwell Automation/Allen-Bradley",
            "product_type": "Programmable Logic Controller",
            "product_name": "1769-L33ER/A CompactLogix",
            "revision": {"major": 32, "minor": 11},
            "serial": "00abc123",
            "name": "Cell5_Controller",
        }

    def get_tag_list(self):
        return [
            {"tag_name": "Speed", "data_type": "REAL", "tag_type": "atomic",
             "dimensions": [0, 0, 0]},
            {"tag_name": "Motor", "data_type": {"name": "MotorUDT"}, "tag_type": "struct",
             "dimensions": [0, 0, 0]},
        ]

    def read(self, *tags):
        out = [Tag(t, self._values.get(t, 0), "REAL", None) for t in tags]
        return out[0] if len(out) == 1 else out

    def write(self, *pairs):
        results = []
        for tag, value in pairs:
            self.written[tag] = value
            self._values[tag] = value
            results.append(Tag(tag, value, "REAL", None))
        return results[0] if len(results) == 1 else results


@pytest.fixture
def eip_target(monkeypatch):
    client = _FakeLogixDriver(values={"Speed": 1500.0, "Setpoint": 42})
    monkeypatch.setattr(conn, "_build_eip_client", lambda target: client)
    target = TargetConfig(name="cell5", protocol="ethernetip", host="10.0.0.9", slot=0)
    return target, client


@pytest.mark.unit
def test_eip_controller_info(eip_target):
    target, _ = eip_target
    out = ops.eip_controller_info(target)
    assert out["controller"]["product_name"] == "1769-L33ER/A CompactLogix"
    assert out["controller"]["name"] == "Cell5_Controller"
    assert out["slot"] == 0


@pytest.mark.unit
def test_eip_list_tags(eip_target):
    target, _ = eip_target
    out = ops.eip_list_tags(target)
    names = {t["name"] for t in out["tags"]}
    assert {"Speed", "Motor"} <= names
    motor = next(t for t in out["tags"] if t["name"] == "Motor")
    assert motor["structure"] is True
    assert motor["data_type"] == "MotorUDT"


@pytest.mark.unit
def test_eip_read_tag(eip_target):
    target, _ = eip_target
    out = ops.eip_read_tag(target, "Speed")
    assert out["value"] == 1500.0
    assert out["good"] is True


@pytest.mark.unit
def test_eip_read_many(eip_target):
    target, _ = eip_target
    out = ops.eip_read_many(target, ["Speed", "Setpoint"])
    values = {i["tag"]: i["value"] for i in out["items"]}
    assert values == {"Speed": 1500.0, "Setpoint": 42}


@pytest.mark.unit
def test_eip_write_dry_run_does_not_write(eip_target):
    target, client = eip_target
    out = ops.eip_write_tag(target, "Setpoint", 99, dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == 42
    assert out["would_write"] == 99
    assert client.written == {}


@pytest.mark.unit
def test_eip_write_applied_captures_before(eip_target):
    target, client = eip_target
    out = ops.eip_write_tag(target, "Setpoint", 99, dry_run=False)
    assert out["applied"] is True
    assert out["before"] == 42  # captured BEFORE value (for undo)
    assert client.written["Setpoint"] == 99
