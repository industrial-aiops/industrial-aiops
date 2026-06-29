"""OEE / downtime / multidim analytics tests over synthetic inputs (no plant)."""

from __future__ import annotations

import pytest

from iaiops.core.brain import oee


@pytest.mark.unit
def test_oee_compute_classic():
    out = oee.oee_compute(
        planned_time_s=28800, run_time_s=25200, ideal_cycle_time_s=2.0,
        total_count=12000, good_count=11800,
    )
    # Availability 25200/28800 = 0.875
    assert out["availability"]["value"] == pytest.approx(0.875, abs=1e-3)
    # Performance (2*12000)/25200 = 0.95238
    assert out["performance"]["value"] == pytest.approx(0.95238, abs=1e-3)
    # Quality 11800/12000 = 0.98333
    assert out["quality"]["value"] == pytest.approx(0.98333, abs=1e-3)
    assert 0.0 < out["oee"] < 1.0
    assert out["oee_pct"] == pytest.approx(out["oee"] * 100, abs=0.05)


@pytest.mark.unit
def test_oee_performance_capped_when_optimistic_cycle():
    out = oee.oee_compute(100, 100, 2.0, 100, 100)  # ideal*total = 200 > run 100
    assert out["performance"]["capped"] is True
    assert out["performance"]["value"] == 1.0
    assert out["performance"]["raw"] > 1.0


@pytest.mark.unit
def test_downtime_events_detects_and_categorizes():
    series = [
        {"timestamp": "2026-06-28T08:00:00Z", "state": "RUNNING"},
        {"timestamp": "2026-06-28T08:05:00Z", "state": "FAULT"},
        {"timestamp": "2026-06-28T08:10:00Z", "state": "RUNNING"},
        {"timestamp": "2026-06-28T08:20:00Z", "state": "changeover"},
        {"timestamp": "2026-06-28T08:35:00Z", "state": "RUNNING"},
    ]
    out = oee.downtime_events(series)
    assert out["event_count"] == 2
    cats = {e["category"] for e in out["events"]}
    assert "mechanical" in cats  # FAULT
    assert "changeover" in cats
    # FAULT span = 5 min = 300s; changeover span = 15 min = 900s
    assert out["total_downtime_s"] == pytest.approx(1200.0, abs=1e-3)
    assert out["by_category"]["mechanical"]["downtime_s"] == pytest.approx(300.0, abs=1e-3)


@pytest.mark.unit
def test_downtime_min_duration_filters():
    series = [
        {"timestamp": "2026-06-28T08:00:00Z", "state": "RUNNING"},
        {"timestamp": "2026-06-28T08:00:10Z", "state": "IDLE"},
        {"timestamp": "2026-06-28T08:00:20Z", "state": "RUNNING"},
    ]
    out = oee.downtime_events(series, min_duration_s=30)
    assert out["event_count"] == 0


@pytest.mark.unit
def test_oee_multidim_aggregates_and_ranks():
    records = [
        {"machine": "M1", "part": "A", "shift": "day", "planned_time_s": 3600,
         "run_time_s": 3600, "ideal_cycle_time_s": 1.0, "total_count": 3600, "good_count": 3600},
        {"machine": "M2", "part": "A", "shift": "day", "planned_time_s": 3600,
         "run_time_s": 1800, "ideal_cycle_time_s": 1.0, "total_count": 1800, "good_count": 1000},
    ]
    out = oee.oee_multidim(records, dimensions=["machine", "part"])
    assert out["group_count"] == 2
    # M1 is near-perfect, M2 is worse → M2 first in worst_performers.
    assert out["worst_performers"][0]["dimensions"]["machine"] == "M2"
    assert out["worst_performers"][-1]["oee"] >= out["worst_performers"][0]["oee"]
