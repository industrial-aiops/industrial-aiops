"""Process control-loop health — oscillation / offset / saturation (pure + tool)."""

import pytest

from iaiops.core.brain.control_loop import control_loop_health
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.process_tools import control_loop_health as control_loop_health_tool


@pytest.mark.unit
def test_saturated_when_op_pinned_high():
    samples = [{"pv": 70, "sp": 75, "op": 100} for _ in range(12)]
    out = control_loop_health(samples)
    assert out["verdict"] == "saturated" and out["opSaturationHighPct"] == 100.0


@pytest.mark.unit
def test_oscillating_when_error_crosses_repeatedly():
    # PV swings above/below SP every sample → high crossing index.
    samples = [{"pv": 75 + (2 if i % 2 == 0 else -2), "sp": 75, "op": 50} for i in range(20)]
    out = control_loop_health(samples)
    assert out["verdict"] == "oscillating" and out["oscillationIndex"] > 0.3


@pytest.mark.unit
def test_offset_when_pv_sits_away_from_sp():
    samples = [{"pv": 70.0, "sp": 75.0, "op": 50} for _ in range(12)]   # steady 5-unit offset
    out = control_loop_health(samples)
    assert out["verdict"] == "offset" and out["meanOffset"] == -5.0


@pytest.mark.unit
def test_ok_when_tracking():
    # PV hovers just above SP (tiny offset well within band, no repeated crossings).
    pvs = [75.02, 75.05, 75.03, 75.06, 75.04, 75.07, 75.02, 75.05, 75.03, 75.06, 75.04, 75.05]
    out = control_loop_health([{"pv": p, "sp": 75.0, "op": 50} for p in pvs])
    assert out["verdict"] == "ok"


@pytest.mark.unit
def test_insufficient_samples():
    out = control_loop_health([{"pv": 1, "sp": 1} for _ in range(4)])
    assert out["verdict"] == "insufficient_data" and out["needed"] == 8


@pytest.mark.unit
def test_tool_is_process_edition_module_and_runs():
    assert "process_tools" not in BRAIN_MODULES
    assert "process_tools" in selected_tool_modules("process")
    assert "process_tools" not in selected_tool_modules("opcua")     # bare protocol
    assert getattr(control_loop_health_tool, "_is_governed_tool", False) is True
    out = control_loop_health_tool(samples=[{"pv": 70, "sp": 75, "op": 100}] * 12)
    assert "error" not in out and out["verdict"] == "saturated"
