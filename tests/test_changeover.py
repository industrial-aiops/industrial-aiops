"""Factory changeover / SMED analysis — pure + tool."""

import pytest

from iaiops.core.brain.changeover import changeover_analysis
from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.factory_tools import changeover_analysis as changeover_analysis_tool

_PARTS = [
    {"timestamp": "2026-07-12T08:00:00Z", "product": "A"},
    {"timestamp": "2026-07-12T08:10:00Z", "product": "A"},
    {"timestamp": "2026-07-12T08:45:00Z", "product": "B"},   # changeover A→B = 35 min = 2100 s
    {"timestamp": "2026-07-12T08:50:00Z", "product": "B"},
    {"timestamp": "2026-07-12T09:30:00Z", "product": "C"},   # changeover B→C = 40 min = 2400 s
]


@pytest.mark.unit
def test_changeovers_measured_between_products():
    out = changeover_analysis(_PARTS)
    assert out["changeover_count"] == 2
    assert out["longest"]["from"] == "B" and out["longest"]["to"] == "C"
    assert out["longest"]["durationS"] == 2400.0
    assert out["totalChangeoverS"] == 4500.0 and out["avgDurationS"] == 2250.0


@pytest.mark.unit
def test_worst_first_ordering():
    order = [(c["from"], c["to"]) for c in changeover_analysis(_PARTS)["changeovers"]]
    assert order == [("B", "C"), ("A", "B")]      # longest first


@pytest.mark.unit
def test_single_product_has_no_changeover():
    out = changeover_analysis([
        {"timestamp": "2026-07-12T08:00:00Z", "product": "A"},
        {"timestamp": "2026-07-12T08:10:00Z", "product": "A"},
    ])
    assert out["changeover_count"] == 0 and out["longest"] is None


@pytest.mark.unit
def test_ignores_bad_records():
    out = changeover_analysis(_PARTS + [{"product": "D"}, {"timestamp": "bad", "product": "E"}])
    assert out["good_parts"] == 5 and out["ignored"] == 2


@pytest.mark.unit
def test_tool_is_factory_edition_module_and_runs():
    assert "factory_tools" not in BRAIN_MODULES
    assert "factory_tools" in selected_tool_modules("factory")
    assert "factory_tools" not in selected_tool_modules("modbus")   # bare protocol
    assert getattr(changeover_analysis_tool, "_is_governed_tool", False) is True
    out = changeover_analysis_tool(good_parts=_PARTS)
    assert "error" not in out and out["changeover_count"] == 2
