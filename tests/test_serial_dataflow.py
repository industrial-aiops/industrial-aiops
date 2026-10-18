"""#249 follow-up 2, applied to the `serial` connector (E4, merged while this was open).

Serial had a per-ref read but no connect probe, so `diag dataflow` answered
`cannot_connect` ("network path down") for an instrument whose link opened fine,
and its profile refusals (no profile, no such channel) read as "wrong address".
Its connect hop is now the doctor probe — open and close the link, send nothing —
and a profile that does not fit is a description cause, as for Modbus and IO-Link.
Serial has no health summary, so the shared health rule does not apply to it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import iaiops.connectors.serial.ops as ops
from iaiops.core.brain import diagnostics
from iaiops.core.runtime.sensor import InvalidReadingError, parse_profile

pytestmark = pytest.mark.unit

PROFILE = parse_profile(
    {
        "id": "scale",
        "protocol": "serial",
        "source": "manual",
        "verified": "待核实",
        "mode": "listen",
        "channels": [
            {
                "name": "weight",
                "layout": {"pattern": r"(?P<status>ST|US),(?P<value>[+-]?\d+\.\d+)kg"},
                "unit": "kg",
                "status": {"field": "status", "ok": ["ST"], "invalid": {"US": "unstable"}},
                "signal": "level",
            }
        ],
    }
)


class _Link:
    opened = 0

    def __init__(self, target, fail: bool = False):
        self.fail = fail

    def open(self):
        if self.fail:
            raise OSError("could not open port /dev/ttyUSB0")
        type(self).opened += 1
        return self

    def close(self):
        return None


@pytest.fixture
def link(monkeypatch):
    _Link.opened = 0
    monkeypatch.setattr(ops, "SerialLink", lambda target: _Link(target))
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: PROFILE)


def _scale(profile: str = "scale.yaml"):
    return SimpleNamespace(
        name="scale1",
        protocol="serial",
        serial_port="/dev/ttyUSB0",
        sensor_profile=profile,
        port_profiles=(),
        stale_after_s=2.0,
        bus="",
        tags=(),
    )


def _description_headline(out: dict, needle: str) -> None:
    assert out["verdict"] == "comms_ok_description_mismatch", out
    assert needle in out["diagnosis"]
    assert "wrong address" not in out["diagnosis"]


def test_the_connect_hop_opens_the_link_and_sends_nothing(link, monkeypatch):
    monkeypatch.setattr(ops, "read_value", lambda t, ref: 12.5)
    out = diagnostics.diagnose_dataflow(_scale(), "ch:weight")
    assert out["hops"][0]["ok"] is True, out["hops"][0]
    assert _Link.opened == 1
    assert out["verdict"] == "healthy"


def test_a_link_that_will_not_open_still_cannot_connect(monkeypatch):
    monkeypatch.setattr(ops, "SerialLink", lambda target: _Link(target, fail=True))
    assert diagnostics.diagnose_dataflow(_scale(), "ch:weight")["verdict"] == "cannot_connect"


def test_no_profile_is_a_description_cause(link):
    _description_headline(diagnostics.diagnose_dataflow(_scale(profile=""), "ch:weight"), "profile")


def test_no_such_channel_is_a_description_cause(link):
    _description_headline(diagnostics.diagnose_dataflow(_scale(), "ch:nope"), "nope")


def test_the_instruments_own_status_stays_a_field_reading_with_its_reason(link, monkeypatch):
    def unstable(t, ref):
        raise InvalidReadingError("weight: status 'US' (unstable).")

    monkeypatch.setattr(ops, "read_value", unstable)
    out = diagnostics.diagnose_dataflow(_scale(), "ch:weight")
    assert out["verdict"] == "comms_ok_bad_quality"
    assert "unstable" in out["diagnosis"]
