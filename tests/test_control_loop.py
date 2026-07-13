"""Process control-loop health — oscillation / offset / saturation (pure + tool)."""

import pytest

from iaiops.core.brain.control_loop import control_loop_health
from iaiops.core.brain.heat_exchanger import heat_exchanger_fouling
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.process_tools import control_loop_health as control_loop_health_tool
from mcp_server.tools.process_tools import heat_exchanger_fouling as heat_exchanger_fouling_tool


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
    samples = [{"pv": 70.0, "sp": 75.0, "op": 50} for _ in range(12)]  # steady 5-unit offset
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
    assert "process_tools" not in selected_tool_modules("opcua")  # bare protocol
    assert getattr(control_loop_health_tool, "_is_governed_tool", False) is True
    out = control_loop_health_tool(samples=[{"pv": 70, "sp": 75, "op": 100}] * 12)
    assert "error" not in out and out["verdict"] == "saturated"


# ── heat_exchanger_fouling ───────────────────────────────────────────────────


def _hx(hot_outs):
    return [{"hot_in": 90, "hot_out": ho, "cold_in": 30} for ho in hot_outs]


@pytest.mark.unit
def test_hx_ok_when_effectiveness_stable():
    out = heat_exchanger_fouling(_hx([55, 55, 56, 55, 54, 55]))  # ε ~0.58, flat
    assert out["verdict"] == "ok" and out["meanEffectiveness"] > 0.5


@pytest.mark.unit
def test_hx_fouling_when_effectiveness_declines():
    # ε goes 0.583 (hot_out 55) → 0.3 (hot_out 72): >10% decline and mean < 0.5.
    out = heat_exchanger_fouling(_hx([55, 55, 55, 72, 72, 72]))
    assert out["verdict"] == "fouling" and out["declinePct"] > 10


@pytest.mark.unit
def test_hx_insufficient_data():
    out = heat_exchanger_fouling(_hx([55, 55, 55]))
    assert out["verdict"] == "insufficient_data" and out["needed"] == 6


@pytest.mark.unit
def test_hx_tool_runs():
    assert getattr(heat_exchanger_fouling_tool, "_is_governed_tool", False) is True
    assert "process_tools" in selected_tool_modules("process")
    out = heat_exchanger_fouling_tool(readings=_hx([55, 55, 55, 72, 72, 72]))
    assert "error" not in out and out["verdict"] == "fouling"
