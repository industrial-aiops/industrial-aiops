"""Binding sensor profiles to endpoints in config.yaml (HLD §16.5 S3).

A Modbus endpoint is one device → one `sensor_profile`. An IO-Link master has a
device per port → `port_profiles: {port: file}`. Paths resolve next to
config.yaml, and every profile is loaded and validated with the config — a broken
profile fails at load, naming the endpoint, not as a week of gaps.
"""

from __future__ import annotations

import pytest
import yaml

from iaiops.core.runtime.config import load_config
from iaiops.core.runtime.sensor.binding import endpoint_profile, port_profile

pytestmark = pytest.mark.unit

MODBUS_PROFILE = {
    "id": "force",
    "protocol": "modbus",
    "source": "manual",
    "verified": "待核实",
    "channels": [
        {
            "name": "fz",
            "layout": {"table": "input", "address": 0, "type": "float32", "order": "ABCD"},
            "unit": "N",
            "signal": "level",
        }
    ],
}
IOLINK_PROFILE = {
    "id": "distance",
    "protocol": "iolink",
    "source": "iodd",
    "verified": "待核实",
    "match": {"vendor_id": 888, "device_id": 4660},
    "channels": [
        {
            "name": "distance",
            "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
            "unit": "mm",
            "signal": "level",
        }
    ],
}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")
    return path


def _config(tmp_path, endpoint):
    return _write(tmp_path / "site" / "config.yaml", {"endpoints": [endpoint]})


def test_modbus_profile_resolves_next_to_config(tmp_path):
    _write(tmp_path / "site" / "profiles" / "force.yaml", MODBUS_PROFILE)
    path = _config(
        tmp_path,
        {
            "name": "cell",
            "protocol": "modbus",
            "host": "h",
            "sensor_profile": "profiles/force.yaml",
        },
    )
    target = load_config(path).get_target("cell")
    assert endpoint_profile(target).channel("fz").unit == "N"


def test_iolink_port_profiles(tmp_path):
    _write(tmp_path / "site" / "tof.yaml", IOLINK_PROFILE)
    path = _config(
        tmp_path,
        {
            "name": "master",
            "protocol": "iolink",
            "agent_url": "http://m",
            "port_profiles": {2: "tof.yaml"},
        },
    )
    target = load_config(path).get_target("master")
    assert port_profile(target, 2).vendor_id == 888
    assert port_profile(target, 3) is None


@pytest.mark.parametrize(
    ("endpoint", "files", "message"),
    [
        (  # missing file
            {"name": "cell", "protocol": "modbus", "host": "h", "sensor_profile": "nope.yaml"},
            {},
            "nope.yaml",
        ),
        (  # invalid profile content, reported with the endpoint
            {"name": "cell", "protocol": "modbus", "host": "h", "sensor_profile": "bad.yaml"},
            {"bad.yaml": {**MODBUS_PROFILE, "verified": "trust me"}},
            "cell",
        ),
        (  # profile protocol ≠ endpoint protocol
            {"name": "cell", "protocol": "modbus", "host": "h", "sensor_profile": "tof.yaml"},
            {"tof.yaml": IOLINK_PROFILE},
            "iolink",
        ),
        (  # port_profiles on a Modbus endpoint
            {"name": "cell", "protocol": "modbus", "host": "h", "port_profiles": {1: "force.yaml"}},
            {"force.yaml": MODBUS_PROFILE},
            "port_profiles",
        ),
        (  # sensor_profile on an IO-Link master
            {
                "name": "m",
                "protocol": "iolink",
                "agent_url": "http://m",
                "sensor_profile": "tof.yaml",
            },
            {"tof.yaml": IOLINK_PROFILE},
            "port_profiles",
        ),
        (  # port out of range
            {
                "name": "m",
                "protocol": "iolink",
                "agent_url": "http://m",
                "port_profiles": {0: "tof.yaml"},
            },
            {"tof.yaml": IOLINK_PROFILE},
            "port",
        ),
    ],
)
def test_bad_bindings_fail_at_load(tmp_path, endpoint, files, message):
    for name, data in files.items():
        _write(tmp_path / "site" / name, data)
    with pytest.raises(ValueError, match=message):
        load_config(_config(tmp_path, endpoint))


def test_profile_match_block_is_iolink_only():
    from iaiops.core.runtime.sensor import parse_profile

    with pytest.raises(ValueError, match="match"):
        parse_profile({**MODBUS_PROFILE, "match": {"vendor_id": 1, "device_id": 2}})
    with pytest.raises(ValueError, match="device_id"):
        parse_profile({**IOLINK_PROFILE, "match": {"vendor_id": 1}})
