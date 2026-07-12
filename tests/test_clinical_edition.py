"""Clinical-facility edition — profile/entrypoint + medical-gas source check (NFPA 99)."""

import pytest

from iaiops.core.brain.clinical_facility import medical_gas_check, or_environment_check
from mcp_server import entrypoints
from mcp_server.profiles import NAMED_PROFILES, selected_tool_modules
from mcp_server.tools.clinical_tools import medical_gas_check as medical_gas_check_tool
from mcp_server.tools.clinical_tools import or_environment_check as or_environment_check_tool


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.unit
def test_clinical_profile_registered():
    assert NAMED_PROFILES["clinical"] == ("bacnet", "modbus", "opcua")
    assert hasattr(entrypoints, "main_clinical")
    assert "clinical" in entrypoints.ENTRYPOINT_SELECTIONS


@pytest.mark.unit
def test_clinical_tools_are_an_edition_module_not_global_brain():
    """The clinical tools load for building & clinical editions — never on a bare
    protocol selection and never in the always-on brain."""
    from mcp_server.profiles import BRAIN_MODULES

    assert "clinical_tools" not in BRAIN_MODULES         # NOT always-on
    assert "clinical_tools" in selected_tool_modules("building")
    assert "clinical_tools" in selected_tool_modules("clinical")
    # A bare bacnet / opcua selection does not pull the edition module.
    assert "clinical_tools" not in selected_tool_modules("bacnet")
    assert "clinical_tools" not in selected_tool_modules("opcua")


_SOURCES = [
    {"system": "OR-1-O2", "gas": "oxygen", "pressure_kpa": 360},          # normal
    {"system": "Ward-O2", "gas": "oxygen", "pressure_kpa": 330},          # low_pressure
    {"system": "ICU-O2", "gas": "oxygen", "pressure_kpa": 300},           # critical (<=310)
    {"system": "OR-Air", "gas": "medical_air", "pressure_kpa": 400},      # high_pressure
    {"system": "ICU-Vac", "gas": "vacuum", "pressure_kpa": -55},          # normal (deep enough)
    {"system": "Ward-Vac", "gas": "vacuum", "pressure_kpa": -30},         # insufficient_vacuum
    {"system": "He", "gas": "helium", "pressure_kpa": 500},               # unknown_gas
]


@pytest.mark.unit
def test_medical_gas_grades_each_status():
    out = medical_gas_check(_SOURCES)
    s = out["summary"]
    assert s["normal"] == 2 and s["low_pressure"] == 1 and s["critical"] == 1
    assert s["high_pressure"] == 1 and s["insufficient_vacuum"] == 1 and s["unknown_gas"] == 1
    assert out["sources_evaluated"] == 7


@pytest.mark.unit
def test_medical_gas_worst_first_and_alarm_count():
    out = medical_gas_check(_SOURCES)
    assert out["worst"]["status"] == "critical"
    # alarms exclude 'normal' and 'unknown_gas'
    assert out["alarm_count"] == 4
    assert out["alarms"][0]["status"] == "critical"


@pytest.mark.unit
def test_vacuum_too_shallow_is_critical():
    out = medical_gas_check([{"system": "V", "gas": "vacuum", "pressure_kpa": -20}])
    assert out["worst"]["status"] == "critical"   # -20 kPa is barely any vacuum


@pytest.mark.unit
def test_missing_pressure_not_graded_normal():
    out = medical_gas_check([{"system": "O2", "gas": "oxygen"}])
    assert out["summary"].get("normal", 0) == 0
    assert out["sources_evaluated"] == 1


@pytest.mark.unit
def test_empty():
    out = medical_gas_check([])
    assert out["sources_evaluated"] == 0 and out["alarm_count"] == 0 and out["worst"] is None


@pytest.mark.unit
def test_tool_governed_registered_and_runs(home):
    assert getattr(medical_gas_check_tool, "_is_governed_tool", False) is True
    assert getattr(medical_gas_check_tool, "_risk_level", "") == "low"
    # Scoped as an edition module (loads with the clinical/building edition).
    assert "clinical_tools" in selected_tool_modules("clinical")
    out = medical_gas_check_tool(sources=_SOURCES)
    assert "error" not in out and out["alarm_count"] == 4
    assert out["worst"]["status"] == "critical"


# ── or_environment_check (ASHRAE 170 OR ventilation) ─────────────────────────

_OR_ROOMS = [
    {"room": "OR-1", "temp_c": 21.0, "humidity_pct": 45, "air_changes_per_hour": 25},  # compliant
    {"room": "OR-2", "temp_c": 26.0, "humidity_pct": 45, "air_changes_per_hour": 25},  # temp high
    {"room": "OR-3", "temp_c": 21.0, "humidity_pct": 18, "air_changes_per_hour": 15},  # RH + ACH
]


@pytest.mark.unit
def test_or_environment_flags_out_of_range_params():
    out = or_environment_check(_OR_ROOMS)
    assert out["rooms_evaluated"] == 3
    assert out["summary"]["compliant"] == 1 and out["summary"]["breach"] == 2
    breaches = {b["room"]: b for b in out["breaches"]}
    assert {f["parameter"] for f in breaches["OR-3"]["flags"]} == {
        "relative humidity", "air changes/hour"}


@pytest.mark.unit
def test_or_environment_empty_and_no_data():
    assert or_environment_check([])["rooms_evaluated"] == 0
    out = or_environment_check([{"room": "OR-x"}])           # no numeric params
    assert out["summary"].get("no_data") == 1


@pytest.mark.unit
def test_or_environment_tool_governed_and_runs():
    assert getattr(or_environment_check_tool, "_is_governed_tool", False) is True
    assert "clinical_tools" in selected_tool_modules("clinical")
    out = or_environment_check_tool(rooms=_OR_ROOMS)
    assert "error" not in out and out["breach_count"] == 2
