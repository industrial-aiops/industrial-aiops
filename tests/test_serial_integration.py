"""E4: serial as a first-class protocol — config, binding, collection, readiness,
the shared probe, the MCP menu and the CLI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

pytestmark = pytest.mark.unit

PROFILE = {
    "id": "scale",
    "protocol": "serial",
    "source": "manual",
    "verified": "待核实",
    "mode": "listen",
    "channels": [
        {
            "name": "weight",
            "layout": {"pattern": r"(?P<status>ST|US),(?P<value>[+-]?\d+\.\d+)(?P<unit>kg)"},
            "unit": "kg",
            "unit_from": "unit",
            "status": {"field": "status", "ok": ["ST"], "invalid": {"US": "unstable"}},
            "signal": "level",
        },
        {
            "name": "loose",
            "layout": {"pattern": r"(?P<value>\d+)(?P<unit>\w+)"},
            "unit_from": "unit",
            "signal": "level",
        },
    ],
}


def _write(tmp_path, endpoint, profile=PROFILE):
    (tmp_path / "scale.yaml").write_text(yaml.safe_dump(profile, allow_unicode=True), "utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"endpoints": [endpoint]}), "utf-8")
    return path


BASE = {
    "name": "scale1",
    "protocol": "serial",
    "serial_port": "/dev/ttyUSB0",
    "sensor_profile": "scale.yaml",
    "stale_after_s": 2,
    "tags": [{"ref": "ch:weight"}],
}


def test_a_serial_endpoint_loads_with_its_profile_and_bus(tmp_path):
    from iaiops.core.runtime.config import load_config

    target = load_config(_write(tmp_path, {**BASE, "bus": "shared"})).get_target("scale1")
    assert target.protocol == "serial" and target.bus == "shared"


def test_a_poll_profile_on_a_shared_or_undeclared_bus_fails_at_load(tmp_path):
    from iaiops.core.runtime.config import load_config

    poll = {**PROFILE, "mode": "poll", "query": "P\r\n"}
    for bus in ("shared", None):
        endpoint = {**BASE, "bus": bus} if bus else dict(BASE)
        with pytest.raises(ValueError, match="dedicated"):
            load_config(_write(tmp_path, endpoint, poll))
    target = load_config(_write(tmp_path, {**BASE, "bus": "dedicated"}, poll)).get_target("scale1")
    assert target.bus == "dedicated"


def test_bus_must_be_shared_or_dedicated(tmp_path):
    from iaiops.core.runtime.config import load_config

    with pytest.raises(ValueError, match="bus"):
        load_config(_write(tmp_path, {**BASE, "bus": "rs485"}))


def _bound(monkeypatch, **extra):
    from iaiops.core.runtime.sensor import parse_profile

    profile = parse_profile(PROFILE)
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: profile)
    return SimpleNamespace(
        name="scale1", protocol="serial", sensor_profile="scale.yaml", port_profiles=(),
        stale_after_s=extra.pop("stale_after_s", 2.0), bus="", tags=(), **extra,
    )  # fmt: skip


def test_serial_is_collectable_and_reasons_are_named(monkeypatch):
    from iaiops.core.collect.reader import can_collect, collectable_reason

    assert can_collect("serial")
    assert collectable_reason(_bound(monkeypatch)) == ""
    assert "stale_after_s" in collectable_reason(_bound(monkeypatch, stale_after_s=0))
    unbound = SimpleNamespace(name="s", protocol="serial", sensor_profile="", stale_after_s=2)
    assert "sensor_profile" in collectable_reason(unbound)


def test_plan_time_refs_and_the_fixed_unit_rule(monkeypatch):
    from iaiops.core.collect.reader import ref_problems

    target = _bound(monkeypatch)
    problems = ref_problems(target, ("ch:weight", "ch:loose", "weight", "ch:nope"))
    assert len(problems) == 3
    assert "fixed unit" in problems[0] and "ch:" in problems[1] and "nope" in problems[2]


def test_unit_for_serial_channels(monkeypatch):
    from iaiops.core.runtime.sensor.binding import unit_for

    target = _bound(monkeypatch)
    assert unit_for(target, "ch:weight") == "kg"
    assert unit_for(target, "ch:loose") == ""


def test_capability_registry_wires_serial():
    from iaiops.core.runtime.capabilities import REGISTRY, UNSUPPORTED

    cap = REGISTRY["serial"]
    for field in ("monitor_read", "read_ref", "session_builder", "session_read"):
        assert getattr(cap, field) is not UNSUPPORTED, field


def test_the_probe_reads_serial(monkeypatch):
    import iaiops.connectors.serial.ops as ops
    from iaiops.core.runtime.sensor.probe import read_channel

    target = _bound(monkeypatch)
    monkeypatch.setattr(ops, "read_value", lambda t, ref: 12.5)
    out = read_channel(target, "ch:weight")
    assert out["levels"] == {"reachable": True, "decodable": True}
    assert (out["value"], out["unit"]) == (12.5, "kg")


def test_menus_and_tool_module():
    from mcp_server import profiles

    assert profiles.PROTOCOL_MODULES["serial"] == "serial_tools"
    assert "serial" in profiles.NAMED_PROFILES["sensor"]
    import mcp_server.tools.serial_tools as tools

    assert getattr(tools.serial_sniff, "_is_governed_tool", False)


def test_cli_serial_sniff_is_registered():
    from iaiops.cli._root import app

    assert "serial" in {group.name for group in app.registered_groups}
