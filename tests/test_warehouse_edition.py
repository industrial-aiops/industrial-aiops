"""Warehouse / intralogistics edition — profile, entrypoint, and material-handling templates."""

import pytest

from iaiops.connectors.modbus import templates
from iaiops.connectors.modbus.templates import _TEMPLATES, list_templates
from mcp_server import entrypoints
from mcp_server.profiles import NAMED_PROFILES


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
