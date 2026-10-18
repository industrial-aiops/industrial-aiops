"""#249 follow-up 4: the master's "process data invalid" is a gap with its reason.

Source: ifm "Operating instructions — IO-Link master with IoT interface AL1352",
80284138/03, 10/2020 (firmware 3.1.x), "IoT Core: Diagnostic codes": code 530,
"The requested data is invalid — Invalid process data". So an ifm IoT-Core
master answers ``pdin/getdata`` with code 530, not 200, when the PD is invalid.

Before, that answer became "the port may be empty, the datapoint unsupported on
this master, or the adr path wrong" — and ``diagnose_dataflow`` turned it into
"wrong address". The device is there and connected; it is reporting that its
own process data is not valid. That is a reading the device refused, so it is a
gap in collection and bad quality in diagnosis, never a value and never a typo.
Other masters (plain-REST flavor): how they flag invalid PD is 待核实, and no
field name is guessed here.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from iaiops.connectors.iolink import client as client_mod
from iaiops.connectors.iolink import ops
from iaiops.connectors.iolink import points as iolink_points
from iaiops.core.brain import diagnostics
from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.reader import read_point
from iaiops.core.collect.runner import run_collection
from iaiops.core.runtime.sensor import InvalidReadingError, is_description_cause, parse_profile

pytestmark = pytest.mark.unit

PDIN = "/iolinkmaster/port[2]/iolinkdevice/pdin/getdata"

TOF = parse_profile(
    {
        "id": "tof",
        "protocol": "iolink",
        "source": "iodd",
        "verified": "待核实",
        "channels": [
            {
                "name": "distance",
                "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                "unit": "mm",
                "signal": "level",
            }
        ],
    }
)


@pytest.fixture
def master(monkeypatch):
    """The real IoLinkClient over a fake HTTP POST: datapoint → (code, value)."""
    tree = {PDIN: (200, "0BB80000")}

    def post(url, payload, timeout):
        code, value = tree.get(payload["adr"], (503, None))
        reply = {"cid": payload["cid"], "code": code}
        if code == 200:
            reply["data"] = {"value": value}
        return json.dumps(reply)

    monkeypatch.setattr(client_mod, "_http_post", post)
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: TOF)
    iolink_points.clear_identity_cache()
    return tree


def _target():
    return SimpleNamespace(
        name="m",
        protocol="iolink",
        agent_url="http://master",
        host="",
        port=80,
        flavor="iotcore",
        timeout_s=2.0,
        port_profiles=((2, "tof.yaml"),),
    )


def test_valid_process_data_decodes(master):
    assert iolink_points.read_value(_target(), "port2/distance") == 3000


def test_invalid_process_data_is_a_refused_reading_with_its_reason(master):
    master[PDIN] = (530, None)
    with pytest.raises(InvalidReadingError, match="process data") as info:
        ops.read_pdin(_target(), 2)
    assert "530" in str(info.value) and "invalid" in str(info.value).lower()
    # The device's own state, not a description problem.
    assert not is_description_cause(info.value)


def test_invalid_process_data_is_a_gap_in_collection(master, tmp_path):
    master[PDIN] = (530, None)
    result = run_collection(
        CollectionPlan(endpoint="m", tags=("port2/distance",), duration_s=1, interval_ms=1000),
        target=_target(),
        reader=read_point,
        db_path=tmp_path / "s.db",
    )
    assert result.samples_written == 0
    (gap,) = result.gaps
    assert "OTNoReadingError" in gap["reason"] and "invalid" in gap["reason"].lower()


def test_invalid_process_data_reads_as_bad_quality_not_a_wrong_address(master, monkeypatch):
    master[PDIN] = (530, None)
    monkeypatch.setattr(diagnostics, "_probe_connect", lambda target: (True, "reachable"))
    out = diagnostics.diagnose_dataflow(_target(), "port2/distance")
    assert out["verdict"] == "comms_ok_bad_quality", out


def test_an_empty_port_is_still_not_called_invalid_process_data(master):
    master[PDIN] = (503, None)  # "no IO-Link device at IO-Link port"
    with pytest.raises(Exception) as info:  # noqa: PT011 — anything but a refused reading
        ops.read_pdin(_target(), 2)
    assert not isinstance(info.value, InvalidReadingError)
    assert "invalid" not in str(info.value).lower()


def test_530_on_another_datapoint_is_not_read_as_process_data(master):
    """530 is also what this master family answers to a failed ISDU read; only
    on pdin does it mean the process data is invalid."""
    master["/iolinkmaster/port[2]/iolinkdevice/vendorid/getdata"] = (530, None)
    out = ops.device_info(_target(), 2)
    assert "vendorid" in out["unavailable"]
    assert "process data" not in out["unavailable"]["vendorid"]
