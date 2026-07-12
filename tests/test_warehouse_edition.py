"""Warehouse / intralogistics edition — profile, entrypoint, and material-handling templates."""

import pytest

from iaiops.connectors.modbus import templates
from iaiops.connectors.modbus.templates import _TEMPLATES, list_templates
from iaiops.core.brain.throughput import line_bottleneck
from mcp_server import entrypoints
from mcp_server.profiles import BRAIN_MODULES, NAMED_PROFILES, selected_tool_modules
from mcp_server.tools.warehouse_tools import line_bottleneck as line_bottleneck_tool

_STATIONS = [
    {"station": "infeed", "throughput_per_hr": 1200},
    {"station": "sorter", "throughput_per_hr": 900, "blocked_pct": 40},
    {"station": "palletizer", "cycle_time_s": 6.0, "starved_pct": 0},   # 3600/6 = 600/hr
]


@pytest.mark.unit
def test_warehouse_profile_registered():
    assert NAMED_PROFILES["warehouse"] == ("eip", "profinet", "modbus", "opcua", "sparkplug")
    # entrypoints auto-generates a main_<profile> shim from the profile menu.
    assert hasattr(entrypoints, "main_warehouse")
    assert "warehouse" in entrypoints.ENTRYPOINT_SELECTIONS


@pytest.mark.unit
def test_material_handling_templates_present():
    names = {t["name"] for t in list_templates()}
    assert {"conveyor_vfd", "agv_battery"} <= names
    assert "conveyor_vfd" in _TEMPLATES and "agv_battery" in _TEMPLATES


@pytest.mark.unit
def test_material_handling_templates_carry_caveat():
    for name in ("conveyor_vfd", "agv_battery"):
        assert "待核实" in templates.get_template(name).caveat   # placeholder maps, honest


@pytest.mark.unit
def test_conveyor_vfd_decodes_scaled_frequency():
    tmpl = templates.get_template("conveyor_vfd")
    block = [0] * tmpl.span
    block[0] = 5000                       # output_frequency at offset 0, uint16 * 0.01
    out = templates.apply_template("conveyor_vfd", block, start_address=tmpl.base_offset)
    decoded = {t["tag"]: t["value"] for t in out["tags"]}
    assert decoded["output_frequency"] == pytest.approx(50.0)


@pytest.mark.unit
def test_agv_battery_decodes_state_of_charge():
    tmpl = templates.get_template("agv_battery")
    block = [0] * tmpl.span
    block[0] = 85                          # state_of_charge at offset 0, uint16 * 1.0
    out = templates.apply_template("agv_battery", block, start_address=tmpl.base_offset)
    decoded = {t["tag"]: t["value"] for t in out["tags"]}
    assert decoded["state_of_charge"] == pytest.approx(85.0)


@pytest.mark.unit
def test_material_handling_template_spans_within_modbus_limit():
    for name in ("conveyor_vfd", "agv_battery"):
        assert 0 < templates.get_template(name).span <= 125


# ── line_bottleneck (warehouse edition tool) ─────────────────────────────────

@pytest.mark.unit
def test_line_bottleneck_is_slowest_station():
    out = line_bottleneck(_STATIONS)
    assert out["bottleneck"]["station"] == "palletizer"
    assert out["bottleneck"]["throughputPerHr"] == 600.0     # 3600 / 6.0 s
    assert out["lineRatePerHr"] == 600.0
    assert out["ranked"][0]["flag"] == "bottleneck"          # slowest sorts first


@pytest.mark.unit
def test_line_bottleneck_flags_blocked_upstream():
    ranked = {r["station"]: r for r in line_bottleneck(_STATIONS)["ranked"]}
    assert ranked["sorter"]["flag"] == "blocked"             # blocked_pct 40 >= 20
    assert ranked["infeed"]["flag"] == "ok"
    assert ranked["sorter"]["vsBottleneckPct"] == 50.0       # 900 vs 600


@pytest.mark.unit
def test_line_bottleneck_near_co_constraint():
    stations = _STATIONS + [{"station": "wrapper", "throughput_per_hr": 620}]  # within 10% of 600
    out = line_bottleneck(stations)
    assert "wrapper" in out["nearBottleneck"]
    assert {r["station"]: r["flag"] for r in out["ranked"]}["wrapper"] == "co_constraint"


@pytest.mark.unit
def test_line_bottleneck_ignores_stations_without_throughput():
    out = line_bottleneck(_STATIONS + [{"station": "no_data"}])
    assert out["stations_analyzed"] == 3 and out["ignored"] == 1


@pytest.mark.unit
def test_line_bottleneck_empty():
    out = line_bottleneck([])
    assert out["stations_analyzed"] == 0 and out["bottleneck"] is None


@pytest.mark.unit
def test_line_bottleneck_is_a_warehouse_edition_module():
    """The tool loads for the warehouse edition only — not a bare protocol, not the brain."""
    assert "warehouse_tools" not in BRAIN_MODULES
    assert "warehouse_tools" in selected_tool_modules("warehouse")
    assert "warehouse_tools" not in selected_tool_modules("modbus")
    assert "warehouse_tools" not in selected_tool_modules("factory")


@pytest.mark.unit
def test_line_bottleneck_tool_governed_and_runs():
    assert getattr(line_bottleneck_tool, "_is_governed_tool", False) is True
    assert getattr(line_bottleneck_tool, "_risk_level", "") == "low"
    out = line_bottleneck_tool(stations=_STATIONS)
    assert "error" not in out and out["bottleneck"]["station"] == "palletizer"
