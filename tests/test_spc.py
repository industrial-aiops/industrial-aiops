"""Fab SPC — Western Electric / Nelson control-chart rules (pure + tool)."""

import pytest

from iaiops.core.brain.spc import spc_check
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.fab_tools import spc_check as spc_check_tool


@pytest.mark.unit
def test_in_control_series():
    series = [10.1, 10.0, 9.9, 10.2, 9.8, 10.1, 9.95, 10.05, 10.0, 9.9]
    out = spc_check(series, target=10.0, sigma=0.15)
    assert out["verdict"] == "in_control" and out["violation_count"] == 0


@pytest.mark.unit
def test_rule1_point_beyond_3sigma():
    series = [10.0, 10.1, 9.9, 10.0, 9.95, 10.05, 10.0, 11.0]  # last point = +6.7σ
    out = spc_check(series, target=10.0, sigma=0.15)
    assert out["verdict"] == "out_of_control"
    assert any(v["rule"] == 1 and v["index"] == 7 for v in out["violations"])


@pytest.mark.unit
def test_rule4_eight_on_one_side():
    series = [10.2, 10.3, 10.1, 10.4, 10.25, 10.15, 10.35, 10.2]  # 8 pts all above center
    out = spc_check(series, target=10.0, sigma=0.5)
    assert any(v["rule"] == 4 for v in out["violations"])


@pytest.mark.unit
def test_capability_reported_with_spec_limits():
    series = [10.0, 10.1, 9.9, 10.05, 9.95, 10.0, 10.02, 9.98, 10.0, 10.01]
    out = spc_check(series, target=10.0, sigma=0.1, usl=10.5, lsl=9.5)
    assert "capability" in out
    assert out["capability"]["cp"] == pytest.approx((10.5 - 9.5) / (6 * 0.1), abs=0.001)


@pytest.mark.unit
def test_insufficient_samples():
    assert spc_check([1, 2, 3])["verdict"] == "insufficient_data"


@pytest.mark.unit
def test_tool_is_fab_edition_module_and_runs():
    assert "fab_tools" not in BRAIN_MODULES
    assert "fab_tools" in selected_tool_modules("fab")
    assert "fab_tools" not in selected_tool_modules("secsgem")       # bare protocol
    assert getattr(spc_check_tool, "_is_governed_tool", False) is True
    out = spc_check_tool(
        series=[10.0, 10.1, 9.9, 10.0, 9.95, 10.05, 10.0, 11.0], target=10.0, sigma=0.15
    )
    assert "error" not in out and out["verdict"] == "out_of_control"
