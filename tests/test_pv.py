"""Renewables PV performance + renewables/plcnext edition wiring (pure + tool)."""

from pathlib import Path

import pytest

from iaiops.core.brain.pv import pv_performance
from mcp_server import entrypoints
from mcp_server.profiles import BRAIN_MODULES, resolve_selection, selected_tool_modules
from mcp_server.tools.renewables_tools import pv_performance as pv_performance_tool

_SKILLS = Path(__file__).resolve().parent.parent / "skills"


@pytest.mark.unit
def test_underperformer_by_irradiance_expected():
    strings = [
        {"string": "S1", "power_w": 5000, "capacity_w": 6000, "irradiance_w_m2": 850},  # ok ~98%
        {"string": "S2", "power_w": 4200, "capacity_w": 6000, "irradiance_w_m2": 850},  # ~82%
    ]
    out = pv_performance(strings)
    by = {u["string"]: u for u in out["underperformers"]}
    assert "S2" in by and by["S2"]["status"] == "underperforming"
    assert by["S2"]["method"] == "expected"
    assert out["worst"]["string"] == "S2"


@pytest.mark.unit
def test_offline_string():
    out = pv_performance([
        {"string": "S1", "power_w": 0, "capacity_w": 6000, "irradiance_w_m2": 800},
    ])
    assert out["underperformers"][0]["status"] == "offline"


@pytest.mark.unit
def test_fleet_median_fallback_when_no_expected():
    # No capacity/irradiance/expected → compare each to the fleet median power.
    strings = [{"string": f"S{i}", "power_w": 5000} for i in range(4)] + \
              [{"string": "LAG", "power_w": 3000}]
    out = pv_performance(strings)
    lag = next(u for u in out["underperformers"] if u["string"] == "LAG")
    assert lag["method"] == "fleet_median" and lag["status"] == "underperforming"


@pytest.mark.unit
def test_empty():
    assert pv_performance([])["strings_evaluated"] == 0


@pytest.mark.unit
def test_pv_tool_is_renewables_edition_module_and_runs():
    assert "renewables_tools" not in BRAIN_MODULES
    assert "renewables_tools" in selected_tool_modules("renewables")
    assert "renewables_tools" not in selected_tool_modules("modbus")   # bare protocol
    assert getattr(pv_performance_tool, "_is_governed_tool", False) is True
    out = pv_performance_tool(
        strings=[{"string": "S", "power_w": 4200, "capacity_w": 6000, "irradiance_w_m2": 850}]
    )
    assert "error" not in out and out["underperformer_count"] == 1


@pytest.mark.unit
def test_renewables_and_plcnext_editions_have_skills():
    assert (_SKILLS / "iaiops-renewables" / "SKILL.md").is_file()
    assert (_SKILLS / "iaiops-plcnext" / "SKILL.md").is_file()


@pytest.mark.unit
def test_plcnext_is_a_packaging_edition_no_edition_module():
    # plcnext reuses opcua+modbus+brain — no edition tool module of its own.
    assert resolve_selection("plcnext") == ["opcua", "modbus"]
    assert hasattr(entrypoints, "main_plcnext")
    modules = selected_tool_modules("plcnext")
    assert not any(m.endswith("_tools") and m in ("renewables_tools", "water_tools",
                   "clinical_tools", "warehouse_tools", "process_tools", "fab_tools",
                   "factory_tools", "building_tools") for m in modules)
