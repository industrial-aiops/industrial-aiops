"""Mitsubishi MC ops tests against a mocked pymcprotocol client.

The pymcprotocol Type3E client is faked by monkeypatching
``connection._build_mc_client`` — exercises session, read/write, and
undo-capture paths without a live PLC.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.mc import ops
from iaiops.core.runtime.config import TargetConfig


class _FakeMCClient:
    """Minimal pymcprotocol Type3E double."""

    def __init__(self, plctype="Q"):
        self.plctype = plctype
        self._words = {"D100": 10, "D101": 20, "D102": 30}
        self._bits = {"M0": True, "M1": False, "M2": True}
        self.written: dict[str, int] = {}

    def connect(self, ip, port):
        self._connected = True

    def close(self):
        self._connected = False

    def read_cputype(self):
        return ("Q06UDV", "0263")

    def batchread_wordunits(self, headdevice, readsize):
        base = int(headdevice[1:])
        return [self._words.get(f"D{base + i}", 0) for i in range(readsize)]

    def batchread_bitunits(self, headdevice, readsize):
        base = int(headdevice[1:])
        return [1 if self._bits.get(f"M{base + i}", False) else 0 for i in range(readsize)]

    def batchwrite_wordunits(self, headdevice, values):
        base = int(headdevice[1:])
        for i, v in enumerate(values):
            self._words[f"D{base + i}"] = v
            self.written[f"D{base + i}"] = v

    def randomread(self, word_devices, dword_devices):
        return ([self._words.get(d, 0) for d in word_devices],
                [self._words.get(d, 0) for d in dword_devices])


@pytest.fixture
def mc_target(monkeypatch):
    client = _FakeMCClient()
    monkeypatch.setattr(conn, "_build_mc_client", lambda target: client)
    return TargetConfig(name="cell3", protocol="mc", host="10.0.0.2", plctype="Q"), client


@pytest.mark.unit
def test_mc_cpu_status(mc_target):
    target, _ = mc_target
    out = ops.mc_cpu_status(target)
    assert out["cpu_type"] == "Q06UDV"
    assert out["plctype"] == "Q"


@pytest.mark.unit
def test_mc_read_words(mc_target):
    target, _ = mc_target
    out = ops.mc_read_words(target, "D100", count=3)
    assert out["words"] == [10, 20, 30]


@pytest.mark.unit
def test_mc_read_bits(mc_target):
    target, _ = mc_target
    out = ops.mc_read_bits(target, "M0", count=3)
    assert out["bits"] == [True, False, True]


@pytest.mark.unit
def test_mc_read_many(mc_target):
    target, _ = mc_target
    out = ops.mc_read_many(target, word_devices=["D100", "D102"], dword_devices=["D101"])
    assert [w["value"] for w in out["words"]] == [10, 30]
    assert out["dwords"][0]["value"] == 20


@pytest.mark.unit
def test_mc_write_dry_run(mc_target):
    target, client = mc_target
    out = ops.mc_write_words(target, "D100", [1, 2], dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == [10, 20]
    assert client.written == {}


@pytest.mark.unit
def test_mc_write_applied_captures_before(mc_target):
    target, client = mc_target
    out = ops.mc_write_words(target, "D100", [1, 2], dry_run=False)
    assert out["applied"] is True
    assert out["before"] == [10, 20]
    assert client.written == {"D100": 1, "D101": 2}
