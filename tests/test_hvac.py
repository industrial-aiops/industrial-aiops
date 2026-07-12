"""Building AHU economizer fault detection — pure + tool."""

import pytest

from iaiops.core.brain.hvac import economizer_check
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.building_tools import economizer_check as economizer_check_tool

# AHU-1 ok (free-cooling); AHU-2 not_economizing; AHU-3 locked_out; AHU-4 simultaneous.
_UNITS = [
    {"ahu": "AHU-1", "oat_c": 12, "rat_c": 23, "oa_damper_pct": 80},
    {"ahu": "AHU-2", "oat_c": 12, "rat_c": 23, "oa_damper_pct": 10, "mech_cooling": True},
    {"ahu": "AHU-3", "oat_c": 25, "rat_c": 23, "oa_damper_pct": 60},
    {"ahu": "AHU-4", "oat_c": 20, "rat_c": 22, "mech_cooling": True, "heating": True},
]


@pytest.mark.unit
def test_each_fault_classified():
    faults = {f["ahu"]: f["status"] for f in economizer_check(_UNITS)["faults"]}
    assert faults["AHU-2"] == "not_economizing"
    assert faults["AHU-3"] == "economizing_when_locked_out"
    assert faults["AHU-4"] == "simultaneous_heat_cool"
    assert "AHU-1" not in faults                       # ok — not a fault


@pytest.mark.unit
def test_summary_and_fault_count():
    out = economizer_check(_UNITS)
    assert out["units_evaluated"] == 4
    assert out["fault_count"] == 3 and out["summary"]["ok"] == 1


@pytest.mark.unit
def test_no_oat_is_no_data():
    out = economizer_check([{"ahu": "X", "rat_c": 22, "oa_damper_pct": 50}])
    assert out["summary"].get("no_data") == 1 and out["fault_count"] == 0


@pytest.mark.unit
def test_tool_is_building_edition_module_and_runs():
    assert "building_tools" not in BRAIN_MODULES
    assert "building_tools" in selected_tool_modules("building")
    assert "building_tools" not in selected_tool_modules("bacnet")   # bare protocol
    assert getattr(economizer_check_tool, "_is_governed_tool", False) is True
    out = economizer_check_tool(units=_UNITS)
    assert "error" not in out and out["fault_count"] == 3
