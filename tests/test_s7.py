"""S7comm ops tests against a mocked pyS7 client.

A real S7 PLC (or sim NIC) is heavy to stand up, so the pyS7 client is faked by
monkeypatching ``connection._build_s7_client``. This still exercises the full
session, address-building, read/write, and undo-capture paths.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.s7 import ops
from iaiops.core.runtime.config import TargetConfig


class _FakeS7Client:
    """Minimal pyS7 S7Client double backed by an address→value dict."""

    def __init__(self, values=None, status="run"):
        self._values = values or {}
        self._status = status
        self.written: dict[str, object] = {}
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def read(self, addresses, optimize=True):
        return [self._values.get(a, 0) for a in addresses]

    def write(self, addresses, values):
        for a, v in zip(addresses, values, strict=False):
            self.written[a] = v
            self._values[a] = v

    def get_cpu_info(self):
        return {"ModuleName": "CPU 1511-1 PN", "SerialNumber": "S123"}

    def get_cpu_status(self):
        return self._status


@pytest.fixture
def s7_target(monkeypatch):
    client = _FakeS7Client(values={"DB1,REAL4": 20.5, "DB1,INT0": 42, "M0.0": True})
    monkeypatch.setattr(conn, "_build_s7_client", lambda target: client)
    target = TargetConfig(name="press1", protocol="s7", host="10.0.0.1", rack=0, slot=1)
    return target, client


@pytest.mark.unit
def test_s7_cpu_info(s7_target):
    target, _ = s7_target
    out = ops.s7_cpu_info(target)
    assert out["cpu_status"] == "run"
    assert out["cpu_info"]["ModuleName"] == "CPU 1511-1 PN"
    assert out["rack"] == 0 and out["slot"] == 1


@pytest.mark.unit
def test_s7_read_db_builds_addresses(s7_target):
    target, _ = s7_target
    out = ops.s7_read_db(target, db=1, dtype="REAL", start=4, count=1)
    assert out["items"][0]["address"] == "DB1,REAL4"
    assert out["items"][0]["value"] == 20.5


@pytest.mark.unit
def test_s7_read_area_stride(s7_target):
    target, client = s7_target
    client._values.update({"DB1,INT0": 1, "DB1,INT2": 2, "DB1,INT4": 3})
    out = ops.s7_read_area(target, area="DB", dtype="INT", start=0, db=1, count=3)
    assert [it["address"] for it in out["items"]] == ["DB1,INT0", "DB1,INT2", "DB1,INT4"]
    assert [it["value"] for it in out["items"]] == [1, 2, 3]


@pytest.mark.unit
def test_s7_read_many(s7_target):
    target, _ = s7_target
    out = ops.s7_read_many(target, ["M0.0", "DB1,INT0"])
    assert out["items"][0]["value"] is True
    assert out["items"][1]["value"] == 42


@pytest.mark.unit
def test_s7_read_area_one_byte_types_use_byte_addresses(s7_target):
    """CHAR/USINT/SINT in non-DB areas must read single bytes, not 16-bit words.

    Regression: these types fell back to the word suffix ('W'), so MB10=0x12,
    MB11=0x34 came back as the overlapping word 0x1234 (4660) instead of 18/52.
    """
    target, client = s7_target
    client._values.update({"MUSINT10": 0x12, "MUSINT11": 0x34, "MUSINT12": 0x56})
    out = ops.s7_read_area(target, area="M", dtype="USINT", start=10, count=3)
    assert [it["address"] for it in out["items"]] == ["MUSINT10", "MUSINT11", "MUSINT12"]
    assert [it["value"] for it in out["items"]] == [0x12, 0x34, 0x56]

    client._values.update({"ISINT5": -3, "ISINT6": 7})
    out = ops.s7_read_area(target, area="I", dtype="SINT", start=5, count=2)
    assert [it["address"] for it in out["items"]] == ["ISINT5", "ISINT6"]
    assert [it["value"] for it in out["items"]] == [-3, 7]

    client._values.update({"QC4": "A", "QC5": "B"})
    out = ops.s7_read_area(target, area="Q", dtype="CHAR", start=4, count=2)
    assert [it["address"] for it in out["items"]] == ["QC4", "QC5"]
    assert [it["value"] for it in out["items"]] == ["A", "B"]


@pytest.mark.unit
def test_s7_read_area_nondb_word_and_float_suffixes(s7_target):
    """Non-DB INT/DINT/REAL/LREAL map to pyS7's exact tokens (MI/MDI/MR/MLR).

    Regression: REAL read as unsigned DWORD (raw bits), INT/DINT lost their
    sign, and LREAL was issued as a 4-byte 'D' read for an 8-byte type.
    """
    target, client = s7_target
    client._values.update({"MLR8": 1.5, "MLR16": -2.25})
    out = ops.s7_read_area(target, area="M", dtype="LREAL", start=8, count=2)
    assert [it["address"] for it in out["items"]] == ["MLR8", "MLR16"]
    assert [it["value"] for it in out["items"]] == [1.5, -2.25]

    client._values.update({"MR20": 20.5})
    out = ops.s7_read_area(target, area="M", dtype="REAL", start=20, count=1)
    assert out["items"][0]["address"] == "MR20"
    assert out["items"][0]["value"] == 20.5

    client._values.update({"MI30": -42, "MDI40": -100000})
    out = ops.s7_read_area(target, area="M", dtype="INT", start=30, count=1)
    assert out["items"][0]["address"] == "MI30"
    out = ops.s7_read_area(target, area="M", dtype="DINT", start=40, count=1)
    assert out["items"][0]["address"] == "MDI40"


@pytest.mark.unit
def test_s7_read_area_unknown_area_raises(s7_target):
    """Unknown areas (timers, counters, typos) must error, never retarget to M.

    Regression: `_AREA_LETTER.get(area, "M")` silently read Merker memory for
    any unknown area — fabricating plausible values from the wrong location.
    """
    target, _ = s7_target
    with pytest.raises(ValueError, match="Unknown S7 area 'T'.*DB.*M.*I/E.*Q/A"):
        ops.s7_read_area(target, area="T", dtype="WORD", start=0, count=1)
    with pytest.raises(ValueError, match="Unknown S7 area"):
        ops.s7_read_area(target, area="X", dtype="BIT", start=0, count=1, bit=0)


@pytest.mark.unit
def test_s7_read_area_unknown_dtype_raises(s7_target):
    """Unknown non-DB dtypes must error instead of silently reading a word."""
    target, _ = s7_target
    with pytest.raises(ValueError, match="not supported for non-DB area"):
        ops.s7_read_area(target, area="M", dtype="STRING", start=0, count=1)


@pytest.mark.unit
def test_s7_write_dry_run_does_not_write(s7_target):
    target, client = s7_target
    out = ops.s7_write_db(target, db=1, dtype="INT", start=0, value=99, dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == 42
    assert out["would_write"] == 99
    assert client.written == {}  # nothing written


@pytest.mark.unit
def test_s7_write_applied_captures_before(s7_target):
    target, client = s7_target
    out = ops.s7_write_db(target, db=1, dtype="INT", start=0, value=99, dry_run=False)
    assert out["applied"] is True
    assert out["before"] == 42  # captured BEFORE value (for undo)
    assert client.written["DB1,INT0"] == 99
