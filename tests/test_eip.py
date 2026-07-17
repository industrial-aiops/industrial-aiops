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
            {
                "tag_name": "Speed",
                "data_type": "REAL",
                "tag_type": "atomic",
                "dimensions": [0, 0, 0],
            },
            {
                "tag_name": "Motor",
                "data_type": {"name": "MotorUDT"},
                "tag_type": "struct",
                "dimensions": [0, 0, 0],
            },
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


# ---------------------------------------------------------------------------
# PCCC (PLC-5 / SLC-500 / MicroLogix) + Micro800 — real hardware behaviour is
# 待核实; these exercise the driver-selection, data-table read/write and
# file-directory paths against a mocked pycomm3 SLCDriver.
# ---------------------------------------------------------------------------

_PCCC_TYPE = {"N": "INT", "F": "REAL", "B": "BOOL", "T": "TIMER", "C": "COUNTER"}


def _pccc_type(addr: str) -> str:
    """Map a data-table address (``N7:0``, ``F8:0``) to a mock element type."""
    return _PCCC_TYPE.get(addr[:1].upper(), "INT")


class _FakeSLCDriver:
    """Minimal pycomm3 SLCDriver double backed by a data-table address→value dict."""

    def __init__(self, values=None):
        self._values = values or {}
        self.written: dict[str, object] = {}
        self.opened = False

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def get_processor_type(self):
        return "1747-L551 5/05"

    def get_file_directory(self):
        return {
            "N7": {"elements": 100, "length": 200},
            "B3": {"elements": 32, "length": 64},
            "F8": {"elements": 10, "length": 40},
        }

    def read(self, *addresses):
        out = [Tag(a, self._values.get(a, 0), _pccc_type(a), None) for a in addresses]
        return out[0] if len(out) == 1 else out

    def write(self, *pairs):
        results = []
        for addr, value in pairs:
            self.written[addr] = value
            self._values[addr] = value
            results.append(Tag(addr, value, _pccc_type(addr), None))
        return results[0] if len(results) == 1 else results


@pytest.fixture
def eip_multi(monkeypatch):
    """Build resolves to a Logix or SLC fake by the target's resolved driver kind.

    Lets a single endpoint be read as Logix (default) or, with plctype='slc',
    over PCCC — proving both the config-level and per-call plctype paths.
    """
    from iaiops.connectors.eip.transport import _resolve_eip_kind

    logix = _FakeLogixDriver(values={"Speed": 1500.0})
    slc = _FakeSLCDriver(values={"N7:0": 42, "F8:0": 3.14, "B3:0/0": 1})

    def build(target):
        return slc if _resolve_eip_kind(target.plctype) == "slc" else logix

    monkeypatch.setattr(conn, "_build_eip_client", build)
    target = TargetConfig(name="ab", protocol="ethernetip", host="10.0.0.5", slot=0)
    return target, logix, slc


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,kind",
    [
        ("", "logix"),
        ("Q", "logix"),  # shared MC default → Logix for EIP
        ("logix", "logix"),
        ("ControlLogix", "logix"),
        ("CompactLogix", "logix"),
        ("slc", "slc"),
        ("SLC-500", "slc"),
        ("plc5", "slc"),
        ("MicroLogix", "slc"),
        ("pccc", "slc"),
        ("micro800", "micro800"),
        ("Micro850", "micro800"),
    ],
)
def test_resolve_eip_kind(raw, kind):
    from iaiops.connectors.eip.transport import _resolve_eip_kind

    assert _resolve_eip_kind(raw) == kind


@pytest.mark.unit
def test_build_selects_driver_class_and_path(monkeypatch):
    """_build_eip_client picks SLCDriver/LogixDriver and the right CIP path per kind."""
    import pycomm3

    import iaiops.connectors.eip.transport as tx

    calls: dict[str, tuple] = {}

    class _SpyLogix:
        def __init__(self, path, **kw):
            calls["logix"] = (path, kw)
            self.socket_timeout = None

    class _SpySLC:
        def __init__(self, path, **kw):
            calls["slc"] = (path, kw)
            self.socket_timeout = None

    monkeypatch.setattr(pycomm3, "LogixDriver", _SpyLogix)
    monkeypatch.setattr(pycomm3, "SLCDriver", _SpySLC)

    # Logix routes through the chassis slot.
    tx._build_eip_client(TargetConfig(name="l", protocol="ethernetip", host="10.0.0.9", slot=2))
    assert calls["logix"][0] == "10.0.0.9/2"

    # SLC/PCCC → SLCDriver, IP only (chassis slot ignored).
    tx._build_eip_client(
        TargetConfig(name="s", protocol="ethernetip", host="10.0.0.9", slot=2, plctype="slc")
    )
    assert calls["slc"][0] == "10.0.0.9"

    # Micro800 → LogixDriver, IP only, program-tag upload skipped.
    tx._build_eip_client(
        TargetConfig(name="m", protocol="ethernetip", host="10.0.0.9", slot=2, plctype="micro800")
    )
    assert calls["logix"][0] == "10.0.0.9"
    assert calls["logix"][1].get("init_program_tags") is False


@pytest.mark.unit
def test_eip_plctype_override_selects_driver(eip_multi):
    """Default reads Logix symbolic tags; plctype='slc' routes to the PCCC driver."""
    target, _logix, _slc = eip_multi
    assert ops.eip_read_tag(target, "Speed")["value"] == 1500.0
    out = ops.eip_read_tag(target, "N7:0", plctype="slc")
    assert out["value"] == 42
    assert out["plctype"] == "slc"


@pytest.mark.unit
def test_eip_effective_target_is_immutable(eip_multi):
    """A per-call plctype override never mutates the passed target (immutable copy)."""
    target, _logix, _slc = eip_multi
    ops.eip_read_tag(target, "N7:0", plctype="slc")
    assert target.plctype == "Q"  # untouched shared default


@pytest.mark.unit
def test_eip_read_pccc_data_table(eip_multi):
    target, _logix, _slc = eip_multi
    assert ops.eip_read_tag(target, "F8:0", plctype="slc")["value"] == 3.14
    assert ops.eip_read_tag(target, "B3:0/0", plctype="slc")["value"] == 1


@pytest.mark.unit
def test_eip_read_many_pccc(eip_multi):
    target, _logix, _slc = eip_multi
    out = ops.eip_read_many(target, ["N7:0", "F8:0"], plctype="slc")
    assert out["plctype"] == "slc"
    values = {i["tag"]: i["value"] for i in out["items"]}
    assert values == {"N7:0": 42, "F8:0": 3.14}


@pytest.mark.unit
def test_eip_controller_info_slc_processor_type(eip_multi):
    target, _logix, _slc = eip_multi
    out = ops.eip_controller_info(target, plctype="slc")
    assert out["plctype"] == "slc"
    assert out["controller"]["processor_type"] == "1747-L551 5/05"
    assert out["info_error"] == ""


@pytest.mark.unit
def test_eip_list_tags_slc_file_directory(eip_multi):
    target, _logix, _slc = eip_multi
    out = ops.eip_list_tags(target, plctype="slc")
    assert out["plctype"] == "slc"
    names = {f["file"] for f in out["files"]}
    assert {"N7", "B3", "F8"} <= names
    n7 = next(f for f in out["files"] if f["file"] == "N7")
    assert n7["elements"] == 100
    assert out["directory_error"] == ""


@pytest.mark.unit
def test_eip_write_pccc_dry_run_does_not_write(eip_multi):
    target, _logix, slc = eip_multi
    out = ops.eip_write_tag(target, "N7:0", 99, plctype="slc", dry_run=True)
    assert out["dry_run"] is True
    assert out["plctype"] == "slc"
    assert out["before"] == 42
    assert out["would_write"] == 99
    assert slc.written == {}


@pytest.mark.unit
def test_eip_write_pccc_applied(eip_multi):
    target, _logix, slc = eip_multi
    out = ops.eip_write_tag(target, "N7:0", 99, plctype="slc", dry_run=False)
    assert out["applied"] is True
    assert out["before"] == 42
    assert slc.written["N7:0"] == 99
