"""Warehouse sortation performance — read-rate / no-read / mis-sort (pure + tool)."""

import pytest

from iaiops.core.brain.sortation import sortation_health
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.warehouse_tools import sortation_health as sortation_health_tool


def _sorts(n_ok=90, n_missort=6, n_no_read=4):
    ok = [{"read": True, "assigned_chute": "C1", "actual_chute": "C1"} for _ in range(n_ok)]
    miss = [{"read": True, "assigned_chute": "C1", "actual_chute": "C9"} for _ in range(n_missort)]
    nr = [{"read": False, "assigned_chute": "C1", "actual_chute": None} for _ in range(n_no_read)]
    return ok + miss + nr


@pytest.mark.unit
def test_rates_from_counts():
    out = sortation_health(_sorts(90, 6, 4))  # 100 items, 96 reads, 6 missorts, 4 no-reads
    assert out["items"] == 100 and out["reads"] == 96
    assert out["noReadRatePct"] == 4.0
    assert out["missortRatePct"] == pytest.approx(6 / 96 * 100, abs=0.01)


@pytest.mark.unit
def test_verdict_high_missort_and_no_read():
    out = sortation_health(_sorts(90, 6, 4))
    assert out["verdict"] == "degraded"  # 4% no-read > 1%, 6.25% missort > 0.5%
    assert out["worstChutes"][0] == {"chute": "C9", "missorts": 6}


@pytest.mark.unit
def test_clean_line_is_ok():
    out = sortation_health([{"read": True, "assigned_chute": "C1", "actual_chute": "C1"}] * 200)
    assert out["verdict"] == "ok" and out["missorts"] == 0 and out["noReads"] == 0


@pytest.mark.unit
def test_empty_is_insufficient():
    assert sortation_health([])["verdict"] == "insufficient"


@pytest.mark.unit
def test_tool_is_warehouse_edition_module_and_runs():
    assert "warehouse_tools" not in BRAIN_MODULES
    assert "warehouse_tools" in selected_tool_modules("warehouse")
    assert getattr(sortation_health_tool, "_is_governed_tool", False) is True
    out = sortation_health_tool(sorts=_sorts())
    assert "error" not in out and out["worstChutes"][0]["chute"] == "C9"
