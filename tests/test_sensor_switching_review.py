"""Defects an adversarial review of E2b found.

1. count_source said "met" when it could not tell (a `di:` ref with no level, a
   `ch:` ref whose profile is unreadable) — "cannot tell" is not "no".
2. Switching channels were listed as "stored without a unit (still 待核实)".
3. A switching channel's `unit` bypassed validation (80 chars, "待核实", lists).
4. response_ms and unknown layout keys were dropped silently.
5. A read of a switching ref returned 1 with nothing saying it means "actuated".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iaiops.core.readiness.sensors import (
    count_source_req,
    decodable_points_req,
    sensor_point_facts,
    switching_count_tags,
)
from iaiops.core.runtime.sensor import parse_profile

pytestmark = pytest.mark.unit


def _profile(layout, **extra):
    return {
        "id": "presence",
        "protocol": "modbus",
        "source": "manual",
        "verified": "bench",
        "channels": [{"name": "part", "layout": layout, "signal": "event", **extra}],
    }


SWITCH = parse_profile(_profile({"table": "discrete", "address": 0, "active": "low"}))


def _target(*tags, profile=""):
    return SimpleNamespace(
        name="line1",
        protocol="modbus",
        sensor_profile=profile,
        port_profiles=(),
        tags=tuple(SimpleNamespace(ref=r, role=role) for r, role in tags),
    )


@pytest.mark.parametrize("ref", ["di:3", "di:3:on", "co:x:high"])
def test_1_a_switching_ref_that_cannot_be_parsed_is_not_reported_as_fine(ref):
    facts = {"switching_count_tags": switching_count_tags((_target((ref, "total_count")),))}
    req = count_source_req(facts)
    assert not req.met and ref in req.detail


def test_1_an_unreadable_profile_cannot_vouch_for_a_ch_counter(monkeypatch):
    def gone(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", gone)
    facts = {
        "switching_count_tags": switching_count_tags(
            (_target(("ch:part", "total_count"), profile="p.yaml"),)
        )
    }
    req = count_source_req(facts)
    assert not req.met and "cannot tell" in req.detail


def test_1_a_register_counter_still_passes():
    facts = {
        "switching_count_tags": switching_count_tags(
            (_target(("hr:4:uint32:ABCD", "total_count")),)
        )
    }
    assert count_source_req(facts).met


def test_2_a_switching_channel_is_not_stored_without_a_unit(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: SWITCH)
    facts = sensor_point_facts((_target(("ch:part", ""), profile="p.yaml"),))
    assert facts["no_unit"] == []
    assert "without a unit" not in decodable_points_req({"sensor_points": facts}).detail


@pytest.mark.parametrize("unit", ["x" * 80, "待核实", "state"])
def test_3_a_switching_channel_takes_no_unit(unit):
    with pytest.raises(ValueError, match="unit"):
        parse_profile(_profile({"table": "discrete", "address": 0, "active": "low"}, unit=unit))


def test_4_response_ms_is_kept_and_unknown_layout_keys_refused():
    channel = parse_profile(
        _profile({"table": "discrete", "address": 0, "active": "high"}, response_ms=5)
    ).channel("part")
    assert channel.response_ms == 5.0
    with pytest.raises(ValueError, match="scale|words"):
        parse_profile(_profile({"table": "discrete", "address": 0, "active": "high", "scale": 2}))


def test_4_active_level_and_table_are_case_insensitive_in_profiles_like_refs():
    channel = parse_profile(
        _profile({"table": "Discrete", "address": 0, "active": "HIGH"})
    ).channel("part")
    assert (channel.layout.table, channel.layout.active) == ("discrete", "high")


def test_4_a_wrong_table_names_the_switch_tables_too():
    with pytest.raises(ValueError, match="discrete"):
        parse_profile(_profile({"table": "relay", "address": 0, "active": "high"}))


def test_5_a_switching_read_says_what_1_means(monkeypatch):
    from iaiops.core.runtime import capabilities
    from iaiops.core.runtime.sensor.probe import read_channel

    cap = capabilities.REGISTRY["modbus"]
    monkeypatch.setitem(
        capabilities.REGISTRY,
        "modbus",
        type(cap)(**{**cap.__dict__, "read_ref": lambda t, r: {"value": 1, "good": True}}),
    )
    out = read_channel(_target(), "di:3:low")
    assert out["active"] == "low" and "actuated" in out["meaning"]
