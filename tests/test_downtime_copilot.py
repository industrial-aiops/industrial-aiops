"""Downtime triage copilot — composes cascade + RCA + PdM into one triage (pure + tool)."""

import pytest

from iaiops.core.brain.downtime_copilot import (
    _cross_check,
    _likely_cause,
    downtime_triage,
)
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.downtime_tools import downtime_triage as downtime_triage_tool


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


_WINDOW = {"start": "2026-06-28T10:00:00Z", "asset": "line1"}
_ALARMS = [
    {"source": "M1_DRIVE", "timestamp": "2026-06-28T09:59:50Z", "message": "motor overload trip"},
    {"source": "M1_DRIVE", "timestamp": "2026-06-28T09:59:53Z", "message": "motor overload trip"},
    {"source": "CONV_02", "timestamp": "2026-06-28T09:59:58Z", "message": "jam detected"},
]
# 40 rising samples toward warn_high=80 → a precursor that was degrading/imminent.
_PRECURSORS = [{
    "signal": "M1_temp",
    "series": [{"value": 60.0 + i * 0.5, "timestamp": f"2026-06-28T09:00:{i % 60:02d}Z"}
               for i in range(40)],
    "warn_high": 80,
}]


@pytest.mark.unit
def test_first_look_is_first_out_of_biggest_cascade():
    out = downtime_triage(_WINDOW, alarms=_ALARMS)
    fl = out["triage"]["first_look"]
    assert fl["source"] == "M1_DRIVE"                 # earliest in the burst
    assert fl["cascade_size"] == 3
    assert out["cascade"]["cascade_count"] == 1


@pytest.mark.unit
def test_likely_cause_is_flattened_from_primary_hypothesis():
    out = downtime_triage(_WINDOW, alarms=_ALARMS)
    lc = out["triage"]["likely_cause"]
    assert lc["cause"] == "mechanical_fault"
    assert lc["verdict"] == "root_cause_identified"
    assert isinstance(lc["confidence"], float) and lc["confidence_band"] == "high"


@pytest.mark.unit
def test_cross_check_corroborated_when_first_out_alarm_is_cited():
    out = downtime_triage(_WINDOW, alarms=_ALARMS)
    cc = out["triage"]["cross_check"]
    assert cc["status"] == "corroborated"
    assert "M1_DRIVE" in cc["detail"]


@pytest.mark.unit
def test_precursors_surface_imminent_trend():
    out = downtime_triage(_WINDOW, alarms=_ALARMS, precursors=_PRECURSORS)
    missed = out["triage"]["precursors_missed"]
    assert missed and missed[0]["signal"] == "M1_temp"
    assert missed[0]["status"] == "imminent" and missed[0]["direction"] == "rising"


@pytest.mark.unit
def test_no_alarms_gives_no_first_look_and_no_alarm_root():
    out = downtime_triage(_WINDOW)
    assert out["triage"]["first_look"] is None
    assert out["triage"]["cross_check"]["status"] == "no_alarm_root"


@pytest.mark.unit
def test_precursor_below_min_samples_is_not_flagged():
    # Only 12 samples < pdm MIN_SAMPLES(30) → insufficient_data → dropped.
    short = [{"signal": "x", "series": [{"value": 60.0 + i} for i in range(12)], "warn_high": 80}]
    out = downtime_triage(_WINDOW, alarms=_ALARMS, precursors=short)
    assert out["triage"]["precursors_missed"] == []


@pytest.mark.unit
def test_cross_check_helper_branches():
    # corroborated / diverging keyed off the primary hypothesis's cited evidence.
    first = {"source": "PT101"}
    corro = {"primary_cause": {"cause": "sensor_fault",
                               "evidence": [{"signal": "alarm", "ref": "PT101"}]}}
    assert _cross_check(first, corro)["status"] == "corroborated"
    diverging = {"primary_cause": {"cause": "power_fault",
                                   "evidence": [{"signal": "alarm", "ref": "BUS_A"}]}}
    assert _cross_check(first, diverging)["status"] == "diverging"
    assert _cross_check(first, {"primary_cause": None})["status"] == "no_rca_primary"
    assert _cross_check(None, corro)["status"] == "no_alarm_root"


@pytest.mark.unit
def test_likely_cause_none_when_no_primary():
    assert _likely_cause({"primary_cause": None}) is None
    assert _likely_cause({}) is None


@pytest.mark.unit
def test_tool_governed_registered_and_runs(home):
    assert getattr(downtime_triage_tool, "_is_governed_tool", False) is True
    assert getattr(downtime_triage_tool, "_risk_level", "") == "low"
    assert "downtime_tools" in BRAIN_MODULES
    out = downtime_triage_tool(window=_WINDOW, alarms=_ALARMS, precursors=_PRECURSORS)
    assert "error" not in out
    assert out["triage"]["first_look"]["source"] == "M1_DRIVE"
    assert out["triage"]["cross_check"]["status"] == "corroborated"
