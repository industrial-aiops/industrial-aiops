"""Fleet / multi-site rollup — pure aggregation + governed MCP tools."""

import pytest

from iaiops.core.brain.fleet import fleet_incident_rollup, fleet_rollup
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.fleet_tools import fleet_incidents, fleet_status


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


# ── fleet_rollup ──────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_status_derived_from_score():
    out = fleet_rollup([
        {"site": "a", "score": 0.95},   # ok
        {"site": "b", "score": 0.7},    # degraded
        {"site": "c", "score": 0.3},    # critical
    ])
    st = {r["site"]: r["status"] for r in out["sites"]}
    assert st == {"a": "ok", "b": "degraded", "c": "critical"}
    assert out["fleet_status"] == "critical"     # worst present
    assert out["by_status"] == {"ok": 1, "degraded": 1, "critical": 1}
    assert out["site_count"] == 3
    assert out["worst_sites"][0]["site"] == "c"  # worst first


@pytest.mark.unit
def test_offline_by_stale_last_seen():
    out = fleet_rollup(
        [{"site": "a", "score": 0.99, "last_seen": "2026-07-11T11:00:00Z"}],
        stale_after_s=300, now="2026-07-11T12:00:00Z",   # 1h old > 5min
    )
    assert out["sites"][0]["status"] == "offline"
    assert out["fleet_status"] == "offline"


@pytest.mark.unit
def test_explicit_status_and_fresh_not_offline():
    out = fleet_rollup(
        [{"site": "a", "status": "degraded", "last_seen": "2026-07-11T11:59:00Z"}],
        stale_after_s=300, now="2026-07-11T12:00:00Z",   # 1min old < 5min
    )
    assert out["sites"][0]["status"] == "degraded"


@pytest.mark.unit
def test_fleet_score_mean_and_skips_unnamed():
    out = fleet_rollup([{"site": "a", "score": 0.8}, {"score": 0.2}, {"site": "b", "score": 0.6}])
    assert out["site_count"] == 2                # the unnamed one is skipped
    assert out["fleet_score"] == 0.7


# ── fleet_incident_rollup ─────────────────────────────────────────────────────
@pytest.mark.unit
def test_incident_rollup():
    out = fleet_incident_rollup([
        {"site": "a", "incidents": [{"cause": "network"}, {"cause": "power"}]},
        {"site": "b", "incidents": [{"primary_cause": "network"}]},
        {"site": "c"},   # no incidents
    ])
    assert out["total_incidents"] == 3
    assert out["sites_with_incidents"] == 2
    assert out["top_causes"][0] == {"cause": "network", "count": 2}


# ── governed MCP tools ────────────────────────────────────────────────────────
@pytest.mark.unit
def test_tools_governed_and_registered():
    for tool in (fleet_status, fleet_incidents):
        assert getattr(tool, "_is_governed_tool", False) is True
        assert getattr(tool, "_risk_level", "") == "low"
    assert "fleet_tools" in BRAIN_MODULES


@pytest.mark.unit
def test_fleet_status_tool(home):
    out = fleet_status(sites=[{"site": "x", "score": 0.9}, {"site": "y", "status": "critical"}])
    assert "error" not in out
    assert out["fleet_status"] == "critical" and out["site_count"] == 2


@pytest.mark.unit
def test_fleet_incidents_tool(home):
    out = fleet_incidents(sites=[{"site": "x", "incidents": [{"cause": "sensor"}]}])
    assert out["total_incidents"] == 1 and out["top_causes"][0]["cause"] == "sensor"
