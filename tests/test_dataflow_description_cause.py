"""#249 follow-up 2: a wrong sensor description is not a field fault.

When the profile does not fit the device — a different sensor on the IO-Link
port, another process-data layout, a ``ch:`` ref with no profile behind it —
``diagnose_dataflow`` said "sensor, field wiring, or source-side fault" or
"wrong address / the point does not exist", and the real reason survived only in
the hop detail. That sends a technician to the field to fix a config file. The
configuration cause is now the headline, with its own verdict, and RCA does not
weigh it as a site fault.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

import iaiops.connectors.iolink.ops as iolink_ops
from iaiops.connectors.iolink import points as iolink_points
from iaiops.core.brain import diagnostics
from iaiops.core.brain.rca import _score_dataflow
from iaiops.core.runtime.sensor import parse_profile

pytestmark = pytest.mark.unit

VERDICT = "comms_ok_description_mismatch"

TOF = parse_profile(
    {
        "id": "tof",
        "protocol": "iolink",
        "source": "iodd",
        "verified": "待核实",
        "match": {"vendor_id": 888, "device_id": 4660},
        "pd_bits": 32,
        "channels": [
            {
                "name": "distance",
                "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                "unit": "mm",
                "invalid": [{"raw": 0xFFFF, "meaning": "no target"}],
                "signal": "level",
            }
        ],
    }
)

FORCE = parse_profile(
    {
        "id": "force",
        "protocol": "modbus",
        "source": "manual",
        "verified": "待核实",
        "channels": [
            {
                "name": "fz",
                "layout": {"table": "input", "address": 4, "type": "float32", "order": "CDAB"},
                "unit": "N",
                "range": [-300, 300],
                "signal": "level",
            }
        ],
    }
)


@pytest.fixture(autouse=True)
def _reachable(monkeypatch):
    monkeypatch.setattr(diagnostics, "_probe_connect", lambda target: (True, "reachable"))
    iolink_points.clear_identity_cache()
    yield
    iolink_points.clear_identity_cache()


@pytest.fixture
def master(monkeypatch):
    state = {"pdin": bytes([0x0B, 0xB8, 0x00, 0x00]), "identity": (888, 4660)}
    monkeypatch.setattr(
        iolink_ops, "read_pdin", lambda target, port: {"bytes": list(state["pdin"])}
    )
    monkeypatch.setattr(
        iolink_ops,
        "device_info",
        lambda target, port: {
            "device": {"vendorid": state["identity"][0], "deviceid": state["identity"][1]}
        },
    )
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: TOF)
    return state


def _iolink():
    return SimpleNamespace(
        name="m", protocol="iolink", agent_url="http://master", port_profiles=((2, "tof.yaml"),)
    )


def _assert_config_headline(out: dict, *needles: str) -> None:
    assert out["verdict"] == VERDICT, out
    text = (out["diagnosis"] + " " + out["recommended_action"]).lower()
    assert "description" in text or "profile" in text
    for needle in needles:
        assert needle in out["diagnosis"], out["diagnosis"]
    # Not phrased as the site's fault.
    assert "wiring" not in text and "wrong address" not in text


def test_a_different_sensor_on_the_port_is_a_description_cause(master):
    master["identity"] = (888, 9999)
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    _assert_config_headline(out, "9999")


def test_another_process_data_layout_is_a_description_cause(master):
    master["pdin"] = bytes(6)  # 48 bits; the profile was written for 32
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    _assert_config_headline(out, "48")


def test_an_identity_in_an_unknown_encoding_is_a_description_cause(master, monkeypatch):
    """The master answered, in an encoding the check cannot read (待核实): the
    profile's identity requirement cannot be applied — not a field fault."""
    monkeypatch.setattr(
        iolink_ops,
        "device_info",
        lambda target, port: {"device": {"vendorid": "acme", "deviceid": "x-1"}},
    )
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    _assert_config_headline(out, "identity")


def test_an_unplugged_sensor_is_a_field_cause_and_rca_weighs_it(master, monkeypatch):
    """Review: a cut cable makes the master REJECT the identity reads (503, no
    device). That was labelled a configuration cause and dropped from RCA."""
    monkeypatch.setattr(
        iolink_ops,
        "device_info",
        lambda target, port: {
            "device": {},
            "unavailable": {
                "vendorid": "IO-Link master rejected '…/vendorid/getdata' with code 503",
                "deviceid": "IO-Link master rejected '…/deviceid/getdata' with code 503",
            },
        },
    )
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    assert out["verdict"] == "comms_ok_bad_quality", out
    assert "no device answered" in out["diagnosis"]
    contributions: dict = {}
    _score_dataflow(out, contributions)
    assert "sensor_fault" in contributions


def test_an_empty_process_data_image_is_not_another_layout(master):
    """Review: 0 bits is "no process data", not "the profile was written for 32"."""
    master["pdin"] = b""
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    assert out["verdict"] == "comms_ok_bad_quality", out
    assert "no process data" in out["diagnosis"]


def test_a_port_with_no_profile_is_a_description_cause(master):
    out = diagnostics.diagnose_dataflow(_iolink(), "port3/distance")
    _assert_config_headline(out, "port 3")


def test_the_sensor_sending_its_own_no_target_code_is_still_a_field_reading(master):
    master["pdin"] = bytes([0xFF, 0xFF, 0x00, 0x00])
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    assert out["verdict"] == "comms_ok_bad_quality"


def _cdab(value: float) -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    return [(c << 8) | d, (a << 8) | b]


@pytest.fixture
def modbus(monkeypatch):
    from iaiops.core.runtime import capabilities as caps

    words = {"input": _cdab(120.0)}

    def reader(target):
        return lambda table, address, count: words[table][:count]

    monkeypatch.setattr(caps, "_modbus_ops_reader", reader)
    return words


def _cell(profile: str = "force.yaml"):
    return SimpleNamespace(name="cell", protocol="modbus", unit_id=1, sensor_profile=profile)


def test_modbus_channel_without_a_profile_is_a_description_cause(modbus):
    out = diagnostics.diagnose_dataflow(_cell(profile=""), "ch:fz")
    _assert_config_headline(out, "sensor_profile")


def test_modbus_unknown_channel_is_a_description_cause(modbus, monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: FORCE)
    out = diagnostics.diagnose_dataflow(_cell(), "ch:fx")
    _assert_config_headline(out, "fx")


def test_modbus_profile_channel_reads_healthy(modbus, monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: FORCE)
    assert diagnostics.diagnose_dataflow(_cell(), "ch:fz")["verdict"] == "healthy"


def test_a_bare_unreadable_address_still_reads_as_wrong_address(monkeypatch):
    from iaiops.core.runtime import capabilities as caps

    def reader(target):
        def read(table, address, count):
            raise OSError("illegal data address")

        return read

    monkeypatch.setattr(caps, "_modbus_ops_reader", reader)
    out = diagnostics.diagnose_dataflow(_cell(profile=""), "40")
    assert out["verdict"] == "comms_ok_value_unreadable"


def test_rca_does_not_weigh_a_description_cause_as_a_site_fault():
    contributions: dict = {}
    _score_dataflow({"verdict": VERDICT, "diagnosis": "profile does not fit"}, contributions)
    assert contributions == {}


def test_a_profile_file_gone_at_read_time_is_a_description_cause(modbus, tmp_path):
    out = diagnostics.diagnose_dataflow(_cell(profile=str(tmp_path / "gone.yaml")), "ch:fz")
    _assert_config_headline(out, "cannot be read")


def test_a_profile_edited_to_another_protocol_is_a_description_cause(modbus, monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: TOF)
    out = diagnostics.diagnose_dataflow(_cell(), "ch:fz")
    _assert_config_headline(out, "iolink profile")


# ── Found on the lab LAN run: the connect hop itself blamed the network ──


def test_iolink_connect_hop_probes_the_master(monkeypatch):
    """IO-Link had no connectivity probe, so `diag dataflow` answered
    `cannot_connect` ("network path down") for a healthy master — and RCA
    weighed that as comms_loss — before any of the verdicts above could run."""
    import json

    from iaiops.connectors.iolink import client as iolink_client
    from iaiops.core.runtime.config import TargetConfig

    tree = {
        "/deviceinfo/productcode/getdata": "AL1352",
        "/iolinkmaster/port[2]/iolinkdevice/vendorid/getdata": 888,
        "/iolinkmaster/port[2]/iolinkdevice/deviceid/getdata": 9999,
        "/iolinkmaster/port[2]/iolinkdevice/pdin/getdata": "0BB80000",
    }

    def post(url, payload, timeout):
        if payload["adr"] in tree:
            return json.dumps({"cid": 1, "code": 200, "data": {"value": tree[payload["adr"]]}})
        return json.dumps({"cid": 1, "code": 503})

    monkeypatch.undo()  # the real connect probe, not the autouse stand-in
    monkeypatch.setattr(iolink_client, "_http_post", post)
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: TOF)
    iolink_points.clear_identity_cache()
    target = TargetConfig(
        name="m", protocol="iolink", agent_url="http://master", port_profiles=((2, "tof.yaml"),)
    )
    out = diagnostics.diagnose_dataflow(target, "port2/distance")
    assert out["hops"][0]["ok"] is True, out["hops"][0]
    _assert_config_headline(out, "9999")


def test_iolink_master_that_is_down_still_cannot_connect(monkeypatch):
    from iaiops.connectors.iolink import client as iolink_client
    from iaiops.core.runtime.config import TargetConfig

    def post(url, payload, timeout):
        raise ConnectionError("refused")

    monkeypatch.undo()
    monkeypatch.setattr(iolink_client, "_http_post", post)
    target = TargetConfig(name="m", protocol="iolink", agent_url="http://master")
    assert diagnostics.diagnose_dataflow(target, "port2/distance")["verdict"] == "cannot_connect"


def test_a_protocol_with_no_connect_probe_is_not_called_unreachable(monkeypatch):
    monkeypatch.undo()
    target = SimpleNamespace(name="plc", protocol="fins", host="10.0.0.9")
    out = diagnostics.diagnose_dataflow(target, "DM100")
    assert out["verdict"] == "no_connect_probe_in_this_build", out
    assert "network" not in out["diagnosis"].lower().split("says nothing")[0]
    contributions: dict = {}
    _score_dataflow(out, contributions)
    assert contributions == {}


def test_a_bad_quality_reading_keeps_the_devices_reason(master):
    """LAN run: for "no target" the read hop said `None` and the diagnosis said
    nothing of the sentinel — the reason the device gave was lost entirely."""
    master["pdin"] = bytes([0xFF, 0xFF, 0x00, 0x00])
    out = diagnostics.diagnose_dataflow(_iolink(), "port2/distance")
    assert out["verdict"] == "comms_ok_bad_quality"
    assert "no target" in out["diagnosis"]
    assert "no target" in out["hops"][1]["detail"]
