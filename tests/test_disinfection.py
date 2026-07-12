"""Water disinfection CT compliance (SWTR) — pure + tool."""

import pytest

from iaiops.core.brain.disinfection import disinfection_ct
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.water_tools import disinfection_ct as disinfection_ct_tool


@pytest.mark.unit
def test_adequate_and_insufficient_basins():
    points = [
        {"location": "CCB-1", "free_chlorine_mg_l": 1.2, "contact_time_min": 30,
         "baffle_factor": 0.7},
        {"location": "CCB-2", "free_chlorine_mg_l": 0.5, "contact_time_min": 10},
    ]
    out = disinfection_ct(points, required_ct=6.0)
    by = {p["location"]: p for p in out["points"]}
    assert by["CCB-1"]["achievedCt"] == pytest.approx(1.2 * 30 * 0.7)   # 25.2
    assert by["CCB-1"]["status"] == "adequate"
    assert by["CCB-2"]["achievedCt"] == pytest.approx(5.0)
    assert by["CCB-2"]["status"] == "insufficient"
    assert out["all_meet_credit"] is False and out["failing_count"] == 1
    assert out["worst"]["location"] == "CCB-2"     # lowest ratio sorts first


@pytest.mark.unit
def test_no_target_and_no_data():
    out = disinfection_ct([
        {"location": "A", "free_chlorine_mg_l": 1.0, "contact_time_min": 20},   # no required
        {"location": "B", "free_chlorine_mg_l": 1.0},                            # missing time
    ])
    statuses = {p["location"]: p["status"] for p in out["points"]}
    assert statuses["A"] == "no_target" and statuses["B"] == "no_data"


@pytest.mark.unit
def test_all_meet_credit_true():
    out = disinfection_ct([{"location": "A", "free_chlorine_mg_l": 2.0, "contact_time_min": 30}],
                          required_ct=6.0)
    assert out["all_meet_credit"] is True and out["failing_count"] == 0


@pytest.mark.unit
def test_tool_is_water_edition_module_and_runs():
    assert "water_tools" not in BRAIN_MODULES
    assert "water_tools" in selected_tool_modules("water")
    assert "water_tools" not in selected_tool_modules("modbus")   # bare protocol
    assert getattr(disinfection_ct_tool, "_is_governed_tool", False) is True
    out = disinfection_ct_tool(
        points=[{"location": "A", "free_chlorine_mg_l": 0.5, "contact_time_min": 10}],
        required_ct=6.0,
    )
    assert "error" not in out and out["failing_count"] == 1
