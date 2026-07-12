"""Clinical-facility isolation-room pressurization compliance (pure + governed tool)."""

import pytest

from iaiops.core.brain.clinical_facility import isolation_room_check
from mcp_server.profiles import NAMED_PROFILES
from mcp_server.tools.bacnet_tools import isolation_room_check as isolation_room_check_tool


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


_ROOMS = [
    {"room": "AII-1", "mode": "negative", "differential_pa": -8.0},   # compliant
    {"room": "AII-2", "mode": "negative", "differential_pa": -1.0},   # breach (< 2.5)
    {"room": "AII-3", "mode": "negative", "differential_pa": 3.0},    # reversed (positive!)
    {"room": "PE-1", "mode": "positive", "differential_pa": 4.0},     # low_margin (2.5..5)
    {"room": "PE-2", "mode": "positive", "differential_pa": 10.0},    # compliant
    {"room": "Lobby", "mode": "neutral", "differential_pa": 0.0},     # info
]


@pytest.mark.unit
def test_summary_counts_each_status():
    out = isolation_room_check(_ROOMS)
    assert out["rooms_evaluated"] == 6
    s = out["summary"]
    assert s["compliant"] == 2 and s["reversed"] == 1
    assert s["breach"] == 1 and s["low_margin"] == 1 and s["info"] == 1


@pytest.mark.unit
def test_reversed_is_worst_and_first():
    out = isolation_room_check(_ROOMS)
    assert out["worst"]["room"] == "AII-3" and out["worst"]["status"] == "reversed"
    order = [b["status"] for b in out["breaches"]]
    assert order == ["reversed", "breach", "low_margin"]   # worst-first
    assert out["breach_count"] == 3


@pytest.mark.unit
def test_reversed_detail_flags_safety_event():
    out = isolation_room_check([{"room": "AII-3", "mode": "negative", "differential_pa": 3.0}])
    row = out["breaches"][0]
    assert row["status"] == "reversed" and "safety event" in row["detail"]


@pytest.mark.unit
def test_positive_room_below_min_is_breach():
    out = isolation_room_check([{"room": "PE-x", "mode": "positive", "differential_pa": 1.0}])
    assert out["worst"]["status"] == "breach"


@pytest.mark.unit
def test_min_magnitude_override():
    # 3 Pa clears the 2.5 minimum (but sits in the 5 Pa low-margin band); raising
    # the required minimum to 5 Pa turns the same room into a breach.
    room = [{"room": "AII", "mode": "negative", "differential_pa": -3.0}]
    assert isolation_room_check(room)["summary"]["low_margin"] == 1
    strict = isolation_room_check(room, min_magnitude_pa=5.0)
    assert strict["summary"]["breach"] == 1


@pytest.mark.unit
def test_missing_reading_is_not_graded_compliant():
    out = isolation_room_check([{"room": "AII", "mode": "negative"}])
    assert out["summary"]["compliant"] == 0
    assert out["rooms_evaluated"] == 1


@pytest.mark.unit
def test_empty():
    out = isolation_room_check([])
    assert out["rooms_evaluated"] == 0 and out["breach_count"] == 0 and out["worst"] is None


@pytest.mark.unit
def test_tool_governed_registered_and_runs(home):
    assert getattr(isolation_room_check_tool, "_is_governed_tool", False) is True
    assert getattr(isolation_room_check_tool, "_risk_level", "") == "low"
    # Scoped to the building edition (BACnet) — not in the always-on global brain.
    assert "bacnet" in NAMED_PROFILES["building"]
    out = isolation_room_check_tool(rooms=_ROOMS)
    assert "error" not in out and out["breach_count"] == 3
    assert out["worst"]["status"] == "reversed"
