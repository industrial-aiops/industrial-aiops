"""IO-Link becomes collectable — through a profile, and only through one (S3).

Before: `pdin` came back as raw hex ("decode per the device's IODD") and IO-Link
had no point-read path at all. Now a ref `port<N>/<channel>` is decoded by the
profile bound to that port. A port with no profile refuses (D44): guessing a
layout gives a plausible wrong number. If the profile names the device it was
written for, the device on the port is checked before decoding.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import iaiops.connectors.iolink.ops as iolink_ops
from iaiops.connectors.iolink import points as iolink_points
from iaiops.core.runtime import capabilities as caps
from iaiops.core.runtime.sensor import parse_profile
from iaiops.core.runtime.session_factory import OTNoReadingError

pytestmark = pytest.mark.unit

PROFILE = parse_profile(
    {
        "id": "distance",
        "protocol": "iolink",
        "source": "iodd",
        "verified": "待核实",
        "match": {"vendor_id": 888, "device_id": 4660},
        "channels": [
            {
                "name": "distance",
                "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                "scale": 0.1,
                "unit": "mm",
                "range": [50, 6000],
                "invalid": [{"raw": 0xFFFF, "meaning": "no target"}],
                "signal": "level",
            }
        ],
    }
)


@pytest.fixture(autouse=True)
def _fresh_identity_cache():
    iolink_points.clear_identity_cache()
    yield
    iolink_points.clear_identity_cache()


@pytest.fixture
def master(monkeypatch):
    """A fake master: pdin bytes and device identity per port."""
    state = {
        "pdin": {2: bytes([0x0B, 0xB8, 0x00, 0x00])},
        "identity": {2: (888, 4660)},
        "calls": [],
    }

    def read_pdin(target, port):
        state["calls"].append(("pdin", port))
        return {"bytes": list(state["pdin"][port])}

    def device_info(target, port):
        state["calls"].append(("identity", port))
        vendor, device = state["identity"][port]
        return {"device": {"vendorid": vendor, "deviceid": device}}

    monkeypatch.setattr(iolink_ops, "read_pdin", read_pdin)
    monkeypatch.setattr(iolink_ops, "device_info", device_info)
    return state


def _target(**profiles):
    return SimpleNamespace(
        name="m",
        protocol="iolink",
        agent_url="http://master",
        port_profiles=tuple((int(k[1:]), v) for k, v in profiles.items()),
    )


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: PROFILE)
    return _target(p2="tof.yaml")


def test_iolink_is_collectable_now():
    from iaiops.core.collect.reader import can_collect

    assert can_collect("iolink")


def test_ref_grammar():
    assert iolink_points.parse_ref("port2/distance") == (2, "distance")
    for bad in ("2/distance", "port/distance", "port0/x", "port33/x", "port2", "port2/"):
        with pytest.raises(ValueError, match="port"):
            iolink_points.parse_ref(bad)


def test_monitor_read_decodes_through_the_port_profile(master, bound):
    value, ts = caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")
    assert value == pytest.approx(300.0)  # 0x0BB8 = 3000 × 0.1
    assert ts == ""


def test_sentinel_is_a_gap(master, bound):
    master["pdin"][2] = bytes([0xFF, 0xFF, 0x00, 0x00])
    with pytest.raises(OTNoReadingError, match="no target"):
        caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")


def test_a_different_device_on_the_port_is_refused(master, bound):
    master["identity"][2] = (888, 9999)
    with pytest.raises(OTNoReadingError, match="9999"):
        caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")


def test_identity_is_checked_once_per_window_not_every_read(master, bound):
    for _ in range(3):
        caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")
    assert master["calls"].count(("identity", 2)) == 1
    assert master["calls"].count(("pdin", 2)) == 3


def test_identity_is_rechecked_after_the_window(master, bound, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(iolink_points, "_now", lambda: clock["t"])
    caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")
    master["identity"][2] = (1, 1)  # sensor swapped
    clock["t"] += iolink_points.IDENTITY_TTL_S + 1
    with pytest.raises(OTNoReadingError):
        caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")


def test_unreadable_identity_refuses_rather_than_skipping_the_check(master, bound):
    master["identity"][2] = ("not-a-number", 4660)
    with pytest.raises(OTNoReadingError, match="identity"):
        caps.REGISTRY["iolink"].monitor_read(bound, "port2/distance")


def test_a_port_without_a_profile_refuses(master, bound):
    with pytest.raises(ValueError, match="port_profiles"):
        caps.REGISTRY["iolink"].monitor_read(bound, "port3/distance")


def test_unknown_channel_refuses(master, bound):
    with pytest.raises(ValueError, match="distance"):
        caps.REGISTRY["iolink"].monitor_read(bound, "port2/force")


def test_read_ref_reports_not_good_for_an_invalid_reading(master, bound):
    master["pdin"][2] = bytes([0xFF, 0xFF, 0x00, 0x00])
    out = caps.REGISTRY["iolink"].read_ref(bound, "port2/distance")
    assert out["good"] is False and out["value"] is None and "no target" in out["reason"]
    master["pdin"][2] = bytes([0x0B, 0xB8, 0x00, 0x00])
    assert caps.REGISTRY["iolink"].read_ref(bound, "port2/distance")["value"] == pytest.approx(
        300.0
    )


def test_an_iolink_endpoint_with_no_profiles_is_not_collectable():
    from iaiops.core.collect.reader import collectable_reason

    assert "port_profiles" in collectable_reason(_target())
    assert collectable_reason(_target(p2="tof.yaml")) == ""


def test_plan_time_ref_problems_for_iolink(bound):
    from iaiops.core.collect.reader import ref_problems

    problems = ref_problems(bound, ("port2/distance", "port3/distance", "port2/force", "2/x"))
    assert len(problems) == 3
    assert "port_profiles" in problems[0] and "distance" in problems[1] and "grammar" in problems[2]
