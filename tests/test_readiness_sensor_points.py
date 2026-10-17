"""Readiness reports, per point, whether a value can be decoded (HLD §16.2, D41).

A bare Modbus address is collected as an unsigned 16-bit word. That is right for
many PLC registers and wrong for every 32-bit, float or signed value — and the
config cannot tell which. So readiness says "N points are untyped": collection
still runs (degraded), but nobody is told the values are understood.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iaiops.core.readiness.sensors import decodable_points_req, sensor_point_facts

pytestmark = pytest.mark.unit


def _tag(ref):
    return SimpleNamespace(ref=ref)


def _modbus(name, *refs, profile=""):
    return SimpleNamespace(
        name=name,
        protocol="modbus",
        sensor_profile=profile,
        port_profiles=(),
        tags=tuple(map(_tag, refs)),
    )


def test_bare_addresses_are_untyped_typed_points_are_decoded():
    facts = sensor_point_facts((_modbus("line1", "40001", "ir:0:float32:CDAB", "hr:3:int16"),))
    assert facts["untyped"] == ["line1:40001"]
    assert facts["decoded"] == 2
    assert facts["unreadable"] == []


def test_refs_the_endpoint_cannot_read_are_listed_with_the_reason():
    facts = sensor_point_facts((_modbus("line1", "ir:0:float32", "ch:fz"),))
    assert len(facts["unreadable"]) == 2
    assert "order" in facts["unreadable"][0] and "sensor_profile" in facts["unreadable"][1]


def test_other_protocols_are_not_judged():
    opcua = SimpleNamespace(name="u", protocol="opcua", tags=(_tag("ns=2;s=x"),))
    assert sensor_point_facts((opcua,)) == {
        "judged_endpoints": 0,
        "decoded": 0,
        "untyped": [],
        "unreadable": [],
        "unverified_profiles": [],
        "no_unit": [],
    }


def test_requirement_is_optional_and_names_the_untyped_points():
    req = decodable_points_req({"sensor_points": sensor_point_facts((_modbus("line1", "40001"),))})
    assert not req.met and req.optional
    assert "line1:40001" in req.detail and "ir:" in req.fix


def test_requirement_met_when_every_point_decodes():
    req = decodable_points_req(
        {"sensor_points": sensor_point_facts((_modbus("l", "ir:0:uint16"),))}
    )
    assert req.met


def test_unverified_profiles_are_named_even_when_met(monkeypatch):
    from iaiops.core.runtime.sensor import parse_profile

    profile = parse_profile(
        {
            "id": "force",
            "protocol": "modbus",
            "source": "datasheet",
            "verified": "待核实",
            "channels": [
                {
                    "name": "fz",
                    "layout": {"table": "input", "address": 0, "type": "int16"},
                    "unit": "N",
                    "signal": "level",
                }
            ],
        }
    )
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: profile)
    facts = sensor_point_facts((_modbus("cell", "ch:fz", profile="force.yaml"),))
    req = decodable_points_req({"sensor_points": facts})
    assert req.met and "force" in req.detail and "待核实" in req.detail


def test_assess_includes_it_under_continuous_collection(tmp_path):
    from iaiops.core.readiness.assess import assess
    from iaiops.core.runtime.config import AppConfig, MonitorTag, TargetConfig

    config = AppConfig(
        targets=(
            TargetConfig(
                name="line1", protocol="modbus", host="h", tags=(MonitorTag(ref="40001"),)
            ),
        )
    )
    report = assess(config, db_path=tmp_path / "none.db")
    collection = next(c for c in report.capabilities if c.key == "continuous_collection")
    keys = [r.key for r in collection.requirements]
    assert "decodable_points" in keys


def test_profile_channels_without_a_confirmed_unit_are_named(monkeypatch):
    from iaiops.core.runtime.sensor import parse_profile

    profile = parse_profile(
        {
            "id": "tof",
            "protocol": "iolink",
            "source": "iodd",
            "verified": "待核实",
            "channels": [
                {
                    "name": "distance",
                    "layout": {"bit_offset": 0, "bit_length": 16, "type": "uint"},
                    "unit": "unitCode 1013 (待核实)",
                    "signal": "level",
                }
            ],
        }
    )
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: profile)
    master = SimpleNamespace(
        name="m",
        protocol="iolink",
        sensor_profile="",
        port_profiles=((2, "tof.yaml"),),
        tags=(_tag("port2/distance"),),
    )
    req = decodable_points_req({"sensor_points": sensor_point_facts((master,))})
    assert "without a unit" in req.detail and "m:port2/distance" in req.detail
