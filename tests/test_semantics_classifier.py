"""Extended semantic-classifier coverage (pure).

Pins the NEW domains/units added to ``_CLASS_HINTS`` (humidity, conductivity, pH,
turbidity, density, mass, valve position, frequency-vs-speed, extra unit tokens)
WITHOUT regressing the classifications the OPC-UA discovery + asset-model layers
already rely on. The legacy assertions live in ``test_opcua_discovery.py`` and
``test_asset_model.py``; the few re-pinned here guard against accidental drift.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.semantics import classify_tag

# ── legacy classifications must NOT change (drift guard) ───────────────────────

@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Temperature", "temperature"),
        ("Inlet_Pressure", "pressure"),
        ("MotorFault", "alarm"),
        ("SpeedSetpoint", "setpoint"),  # setpoint precedes every quantity
        ("RunState", "state"),
        ("FlowRate", "flow"),
        ("kWh_Total", "energy"),  # energy precedes counter
        ("voltage_l1", "voltage"),
        ("aux_relay", "other"),
        ("fl", "other"),  # cryptic, stays other (asset-model relies on this)
        ("Xy", "other"),
    ],
)
def test_legacy_classifications_unchanged(name, expected):
    assert classify_tag(name) == expected


# ── new domains ────────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        # humidity
        ("Zone1_Humidity", "humidity"),
        ("AmbientRH_pct", "humidity"),
        ("DewPoint", "humidity"),
        # conductivity
        ("Loop_Conductivity", "conductivity"),
        ("Outlet_EC", "conductivity"),
        # pH (underscore-guarded so 'phase'/'graph' don't false-match)
        ("Tank_pH", "ph"),
        ("pH_Value", "ph"),
        # turbidity
        ("Filtrate_Turbidity", "turbidity"),
        ("Turbidity_NTU", "turbidity"),
        # density
        ("Slurry_Density", "density"),
        ("ProductSpecificGravity", "density"),
        # mass / weight
        ("Hopper_Weight", "mass"),
        ("NetMass_kg", "mass"),
        ("Silo_LoadCell", "mass"),
        # valve position / opening → position class
        ("CV101_ValvePosition", "position"),
        ("Inlet_Opening", "position"),
        # frequency vs speed disambiguation
        ("VFD_Output_Hz", "frequency"),
        ("Line_Frequency", "frequency"),
        ("Motor_RPM", "speed"),
        ("ConveyorSpeed", "speed"),
    ],
)
def test_new_domain_classifications(name, expected):
    assert classify_tag(name) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    [
        # bare "gram" must NOT match mass — these are common PLC/recipe tag names
        "ProgramNumber", "ProgramStep", "RecipeProgram", "Histogram", "Telegram",
        "Diagram",
        # bare "conduct" must NOT match conductivity
        "Conductor_Status", "ConductTest",
        # bare "ntu" must NOT match turbidity
        "Adventure_Mode", "Continue_Flag",
    ],
)
def test_overbroad_substrings_do_not_false_match(name):
    """Guard against the substring false-matches the classifier-extension review found."""
    assert classify_tag(name) not in ("mass", "conductivity", "turbidity")


# ── extra unit-token hints ─────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Reactor_degC", "temperature"),
        ("Coolant_°C", "temperature"),
        ("Heater_°F", "temperature"),
        ("Header_kPa", "pressure"),
        ("Vacuum_mbar", "pressure"),
        ("Gas_m3h", "flow"),
    ],
)
def test_unit_token_hints(name, expected):
    assert classify_tag(name) == expected


@pytest.mark.unit
def test_blank_and_none_are_other():
    assert classify_tag("") == "other"
    assert classify_tag(None) == "other"  # type: ignore[arg-type]
