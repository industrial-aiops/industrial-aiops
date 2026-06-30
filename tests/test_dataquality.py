"""Data-quality watchdog tests over synthetic feeds (no live systems).

Exercises the data-trust scoring (staleness / dead-heartbeat / bad-quality /
flatline / gaps / anomaly), the per-endpoint and fleet rollups, and the
first-class heartbeat liveness check — all deterministic via a pinned `now`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import dataquality as dq

NOW = datetime(2026, 6, 29, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── heartbeat_health ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_heartbeat_alive_when_advancing():
    out = dq.heartbeat_health([1, 2, 3, 4, 5])
    assert out["alive"] is True
    assert out["distinct_transitions"] == 4


@pytest.mark.unit
def test_heartbeat_dead_when_flatline():
    out = dq.heartbeat_health([7, 7, 7, 7])
    assert out["alive"] is False
    assert "flatline" in out["reason"]


@pytest.mark.unit
def test_heartbeat_stall_exceeds_max_interval():
    base = datetime(2026, 6, 29, 12, 0, 0, tzinfo=UTC)
    series = [
        {"value": 1, "timestamp": _iso(base)},
        {"value": 1, "timestamp": _iso(base + timedelta(seconds=30))},  # stalled 30s
        {"value": 2, "timestamp": _iso(base + timedelta(seconds=31))},
    ]
    out = dq.heartbeat_health(series, max_interval_s=10)
    assert out["longest_stall_s"] == 30.0
    assert out["alive"] is False  # stalled beyond max_interval_s


@pytest.mark.unit
def test_heartbeat_too_few_samples():
    assert dq.heartbeat_health([5])["alive"] is False


# ─── data_quality_scorecard ──────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_feeds_error():
    assert "error" in dq.data_quality_scorecard([])


@pytest.mark.unit
def test_healthy_feed_scores_100():
    feeds = [{"endpoint": "line1", "tags": [
        {"ref": "temp", "samples": [{"value": v, "timestamp": _iso(NOW - timedelta(seconds=s))}
                                    for v, s in [(20, 30), (21, 20), (22, 10), (23, 0)]]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    assert out["fleet_score"] == 100.0
    assert out["fleet_status"] == "ok"
    assert out["worst_tags"] == []


@pytest.mark.unit
def test_dead_heartbeat_is_worst():
    feeds = [{"endpoint": "line1", "tags": [
        {"ref": "hb", "heartbeat": True, "samples": [5, 5, 5, 5]},
        {"ref": "temp", "samples": [{"value": v, "timestamp": _iso(NOW - timedelta(seconds=s))}
                                    for v, s in [(20, 3), (21, 2), (22, 1), (23, 0)]]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    hb = next(t for t in out["worst_tags"] if t["ref"] == "hb")
    assert "dead_heartbeat" in hb["flags"]
    assert hb["score"] == 0
    assert hb["status"] == "dead"
    assert out["issue_breakdown"]["dead_heartbeat"] == 1


@pytest.mark.unit
def test_staleness_flagged_against_pinned_now():
    feeds = [{"endpoint": "line1", "tags": [
        {"ref": "old", "expected_update_s": 60,
         "samples": [{"value": 1, "timestamp": _iso(NOW - timedelta(seconds=600))}]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    tag = out["worst_tags"][0]
    assert "stale" in tag["flags"]
    assert tag["age_seconds"] == 600.0
    assert tag["score"] == 100 - dq.DEDUCTIONS["stale"]


@pytest.mark.unit
def test_bad_quality_all_samples():
    feeds = [{"endpoint": "line1", "tags": [
        {"ref": "bad", "samples": [{"value": None, "good": False} for _ in range(4)]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    assert "bad_quality" in out["worst_tags"][0]["flags"]


@pytest.mark.unit
def test_non_heartbeat_flatline_is_milder_than_dead_heartbeat():
    feeds = [{"endpoint": "l", "tags": [
        {"ref": "flat", "samples": [5, 5, 5, 5]},  # not a heartbeat → flatline, not dead
        {"ref": "hb", "heartbeat": True, "samples": [5, 5, 5, 5]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    flat = next(t for t in out["worst_tags"] if t["ref"] == "flat")
    hb = next(t for t in out["worst_tags"] if t["ref"] == "hb")
    assert "flatline" in flat["flags"] and "dead_heartbeat" not in flat["flags"]
    assert flat["score"] > hb["score"]


@pytest.mark.unit
def test_fleet_rollup_ranks_worst_endpoint():
    feeds = [
        {"endpoint": "good", "tags": [{"ref": "a", "samples": [1, 2, 3, 4]}]},
        {"endpoint": "bad", "tags": [
            {"ref": "hb", "heartbeat": True, "samples": [1, 1, 1, 1]}]},
    ]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    assert out["worst_endpoints"][0]["endpoint"] == "bad"
    assert out["worst_endpoints"][0]["status"] == "dead"
    assert out["endpoints"][0]["status_counts"]  # rollup present
    assert out["evaluated_endpoints"] == 2


@pytest.mark.unit
def test_gap_detection():
    base = NOW - timedelta(minutes=30)
    samples = [
        {"value": 1, "timestamp": _iso(base)},
        {"value": 2, "timestamp": _iso(base + timedelta(seconds=5))},
        {"value": 3, "timestamp": _iso(base + timedelta(seconds=600))},  # 595s gap
    ]
    feeds = [{"endpoint": "l", "tags": [{"ref": "g", "expected_update_s": 30, "samples": samples}]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    assert "gappy" in out["worst_tags"][0]["flags"]
