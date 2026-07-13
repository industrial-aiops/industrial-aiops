"""Alarm-cascade collapse — temporal grouping + first-out root (pure + governed tool)."""

import pytest

from iaiops.core.brain.alarm_flood import alarm_cascade
from mcp_server.tools.alarm_tools import alarm_cascade as alarm_cascade_tool


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


# Two bursts separated by a > window quiet gap; PT101 chatters in the first burst.
_EVENTS = [
    {"source": "PT101", "timestamp": "2026-06-28T10:00:00Z"},  # root of cascade 1
    {"source": "PT101", "timestamp": "2026-06-28T10:00:03Z"},  # chattering
    {"source": "FIC101", "timestamp": "2026-06-28T10:00:05Z"},
    {"source": "LIC101", "timestamp": "2026-06-28T10:00:10Z"},
    {"source": "TT201", "timestamp": "2026-06-28T10:05:00Z"},  # root of cascade 2 (5-min gap)
    {"source": "TT202", "timestamp": "2026-06-28T10:05:05Z"},
]


@pytest.mark.unit
def test_two_cascades_and_first_out_root():
    out = alarm_cascade(_EVENTS, window_s=60)
    assert out["cascade_count"] == 2 and out["total_activations"] == 6
    biggest = out["cascades"][0]  # sorted by size desc
    assert biggest["size"] == 4 and biggest["distinct_sources"] == 3
    assert biggest["root"] == {"source": "PT101", "ts": "2026-06-28T10:00:00+00:00"}
    assert biggest["chattering"] == ["PT101"]
    assert biggest["span_s"] == 10.0
    smaller = out["cascades"][1]
    assert smaller["root"]["source"] == "TT201" and smaller["size"] == 2


@pytest.mark.unit
def test_min_cascade_filters_small_bursts():
    out = alarm_cascade(_EVENTS, window_s=60, min_cascade=3)
    assert out["cascade_count"] == 1  # the 2-alarm cascade is dropped
    assert out["cascades"][0]["root"]["source"] == "PT101"


@pytest.mark.unit
def test_wider_window_merges_into_one_cascade():
    out = alarm_cascade(_EVENTS, window_s=600)  # 5-min gap < 10-min window → one cascade
    assert out["cascade_count"] == 1 and out["cascades"][0]["size"] == 6


@pytest.mark.unit
def test_empty():
    assert alarm_cascade([])["cascade_count"] == 0
    assert alarm_cascade([{"no": "timestamp"}])["total_activations"] == 0


@pytest.mark.unit
def test_tool_governed_and_runs(home):
    assert getattr(alarm_cascade_tool, "_is_governed_tool", False) is True
    assert getattr(alarm_cascade_tool, "_risk_level", "") == "low"
    out = alarm_cascade_tool(events=_EVENTS, window_s=60)
    assert "error" not in out and out["cascade_count"] == 2
