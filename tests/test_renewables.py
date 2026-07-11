"""Renewables (solar/wind) edition — semantics, profile, and a wind-turbine template."""

import pytest

from iaiops.connectors.modbus.templates import _TEMPLATES, list_templates
from iaiops.core.brain.semantics import classify_tag
from mcp_server import entrypoints
from mcp_server.profiles import NAMED_PROFILES


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("plant.irradiance_poa", "irradiance"),
        ("GHI_sensor", "irradiance"),
        ("turbine.wind_speed", "wind_speed"),
        ("风速", "wind_speed"),
        ("blade_pitch_angle", "pitch_angle"),
        ("nacelle_yaw_position", "yaw_angle"),
        ("battery_soc_", "state_of_charge"),
        ("rotor_speed_rpm", "rotor_speed"),
    ],
)
def test_solar_wind_semantics(name, expected):
    assert classify_tag(name) == expected


@pytest.mark.unit
def test_wind_speed_beats_generic_speed():
    # "wind_speed" contains "speed" but must classify as the specific renewables class.
    assert classify_tag("wind_speed") == "wind_speed"
    assert classify_tag("motor_rpm") == "speed"   # generic speed still works


@pytest.mark.unit
def test_renewables_profile_registered():
    assert NAMED_PROFILES["renewables"] == ("modbus", "opcua", "sparkplug")
    # entrypoints auto-generates a main_<profile> shim.
    assert hasattr(entrypoints, "main_renewables")
    assert "renewables" in entrypoints.ENTRYPOINT_SELECTIONS


@pytest.mark.unit
def test_wind_turbine_template_present():
    assert "generic_wind_turbine" in _TEMPLATES
    names = {t["name"] for t in list_templates()}
    assert "generic_wind_turbine" in names
    # PV inverter templates already ship — renewables reuses them.
    assert {"huawei_sun2000_inverter", "growatt_inverter"} <= names
