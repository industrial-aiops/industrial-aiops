"""Water treatment edition (水处理, backlog A9) — profile / entrypoint / semantics /
Modbus templates.

Pins the `water` contract other artifacts assume (skills/iaiops-water,
`iaiops[water]` extra, `iaiops-mcp-water` console script): protocols exactly
modbus + opcua + hart (+ the always-on brain), water-domain semantic classes
(DO / ORP / chlorine / ammonia / TSS / TMP / dosing / aeration / UV), and the
water-industry register templates with their honest 待核实 caveats.
"""

from __future__ import annotations

import struct
import tomllib
from pathlib import Path

import pytest

from iaiops.connectors.modbus import templates
from iaiops.core.brain.semantics import classify_tag
from mcp_server import entrypoints
from mcp_server.profiles import (
    BRAIN_MODULES,
    NAMED_PROFILES,
    resolve_selection,
    selected_tool_modules,
)

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

_WATER_TEMPLATES = ("eh_promag_flowmeter", "hach_sc_controller", "generic_dosing_pump")


# ── profile ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_water_profile_resolves_to_modbus_opcua_hart():
    assert NAMED_PROFILES["water"] == ("modbus", "opcua", "hart")
    assert resolve_selection("water") == ["modbus", "opcua", "hart"]


@pytest.mark.unit
def test_water_profile_tool_modules_are_brain_plus_edition_plus_three_protocols():
    modules = selected_tool_modules("water")
    # brain first, then the water edition module, then the three protocol modules.
    assert modules == (
        list(BRAIN_MODULES) + ["water_tools", "modbus_tools", "opcua_tools", "hart_tools"]
    )


# ── entrypoint + extra ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_water_entrypoint_shim_exists():
    assert "water" in entrypoints.ENTRYPOINT_SELECTIONS
    assert callable(entrypoints.main_water)


@pytest.mark.unit
def test_water_console_script_and_extra_declared():
    project = tomllib.loads(_PYPROJECT.read_text())["project"]
    assert project["scripts"]["iaiops-mcp-water"] == "mcp_server.entrypoints:main_water"
    # The extra references the per-protocol extras (no duplicated version pins).
    water_extra = project["optional-dependencies"]["water"]
    assert sorted(water_extra) == ["iaiops[hart]", "iaiops[modbus]", "iaiops[opcua]"]


@pytest.mark.unit
def test_water_shim_injects_selection(monkeypatch):
    seen: dict[str, str | None] = {}

    def _fake_main() -> None:
        import os

        seen["env"] = os.environ.get("IAIOPS_MCP")

    monkeypatch.setattr(entrypoints.server, "main", _fake_main)
    monkeypatch.delenv("IAIOPS_MCP", raising=False)
    entrypoints.main_water()
    assert seen["env"] == "water"
    assert resolve_selection(seen["env"]) == ["modbus", "opcua", "hart"]


# ── semantics: water-domain tag classes ─────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        # the four contract tags from the A9 spec
        ("pH_01", "ph"),
        ("DO_basin2", "dissolved_oxygen"),
        ("余氯出水", "chlorine"),
        ("TMP_membrane3", "membrane_pressure"),
        # dissolved oxygen / ORP
        ("溶解氧_生化池", "dissolved_oxygen"),
        ("Basin_ORP_", "orp"),
        ("Redox_Probe", "orp"),
        ("氧化还原电位", "orp"),
        # chlorine / ammonia / suspended solids
        ("Free_Chlorine_mgL", "chlorine"),
        ("总氯_出水", "chlorine"),
        ("氨氮_在线", "ammonia"),
        ("NH3_Analyzer", "ammonia"),
        ("MLSS_AerationBasin", "suspended_solids"),
        ("悬浮物浓度", "suspended_solids"),
        ("Effluent_TSS_", "suspended_solids"),
        # membrane pressure (跨膜压差)
        ("跨膜压差_1", "membrane_pressure"),
        ("Transmembrane_Pressure", "membrane_pressure"),
        # UV disinfection
        ("UV_Intensity_Ch1", "uv_intensity"),
        ("紫外强度", "uv_intensity"),
        # equipment: dosing (加药) + aeration blower (曝气风机)
        ("DosingPump_Output", "dosing"),
        ("加药泵02", "dosing"),
        ("曝气量", "aeration"),
        ("Blower_Discharge", "aeration"),
        ("鼓风机1", "aeration"),
        # Chinese unit-style hints on existing classes
        ("进水流量", "flow"),
        ("集水井液位", "level"),
        ("Turbidity_NTU", "turbidity"),
    ],
)
def test_water_domain_classifications(name, expected):
    assert classify_tag(name) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        # bare "do"/"tmp" stay guarded — no confident-but-wrong water labels
        ("Cool_Down_Hours", "runtime"),  # '_do' alone must not mean dissolved oxygen
        ("Outdoor_Temp", "temperature"),
        ("ShutdownFault", "alarm"),
        # legacy quantities keep their classes despite the new water block
        ("Inlet_Pressure", "pressure"),
        ("FlowRate", "flow"),
        ("Tank_pH", "ph"),
    ],
)
def test_water_hints_do_not_regress_existing_classes(name, expected):
    assert classify_tag(name) == expected


# ── Modbus register templates ───────────────────────────────────────────────────

@pytest.mark.unit
def test_water_templates_listed_with_honest_caveats():
    listed = {t["name"]: t for t in templates.list_templates()}
    for name in _WATER_TEMPLATES:
        assert name in listed, f"missing water template {name}"
        assert "待核实" in listed[name]["caveat"], f"{name} must carry a 待核实 caveat"
        assert listed[name]["tag_count"] > 0
        assert 0 < listed[name]["span_registers"] <= 125  # single Modbus read


@pytest.mark.unit
def test_water_templates_validate_against_catalog_shape():
    for name in _WATER_TEMPLATES:
        tmpl = templates.get_template(name)
        assert tmpl.register_type in ("holding", "input")
        offsets = [t.offset for t in tmpl.tags]
        assert len(set(offsets)) == len(offsets), f"{name}: overlapping tag offsets"


@pytest.mark.unit
def test_promag_template_decodes_float_block():
    tmpl = templates.get_template("eh_promag_flowmeter")
    # 5 float32 ABCD values: flow=125.5, mass=980.25, cond=850.0, temp=18.5, tot=42.0
    values = [125.5, 980.25, 850.0, 18.5, 42.0]
    regs: list[int] = []
    for v in values:
        hi, lo = struct.unpack(">HH", struct.pack(">f", v))
        regs.extend([hi, lo])
    out = templates.apply_template("eh_promag_flowmeter", regs, start_address=tmpl.base_offset)
    decoded = {t["tag"]: t["value"] for t in out["tags"]}
    assert decoded["volume_flow"] == pytest.approx(125.5)
    assert decoded["temperature"] == pytest.approx(18.5)
    assert "待核实" in out["caveat"]


@pytest.mark.unit
def test_dosing_pump_template_decodes_mixed_types():
    # 3 float32 (flow, setpoint, stroke %) + 2 uint16 (status, alarm word)
    regs: list[int] = []
    for v in (12.5, 15.0, 83.0):
        hi, lo = struct.unpack(">HH", struct.pack(">f", v))
        regs.extend([hi, lo])
    regs.extend([1, 0])  # running, no alarms
    out = templates.apply_template("generic_dosing_pump", regs, start_address=0)
    decoded = {t["tag"]: t for t in out["tags"]}
    assert decoded["dosing_flow"]["value"] == pytest.approx(12.5)
    assert decoded["stroke_rate"]["value"] == pytest.approx(83.0)
    assert decoded["stroke_rate"]["unit"] == "%"
    assert decoded["pump_status"]["value"] == 1
    assert decoded["alarm_word"]["value"] == 0
