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


# ─── configurable staleness per tag / feed ───────────────────────────────────


@pytest.mark.unit
def test_tag_staleness_s_overrides_default_and_expected():
    # A slow daily counter: 1h old is fine when it carries its own staleness budget.
    feeds = [{"endpoint": "l", "tags": [
        {"ref": "daily", "staleness_s": 90000, "expected_update_s": 30,
         "samples": [{"value": 1, "timestamp": _iso(NOW - timedelta(seconds=3600))}]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    tag = out["endpoints"][0]["worst_tag"]
    # 3600s old but staleness budget is 90000s → NOT stale, score stays 100.
    assert out["fleet_score"] == 100.0
    assert tag is None or "stale" not in tag["flags"]


@pytest.mark.unit
def test_feed_level_staleness_applies_when_tag_silent():
    feeds = [{"endpoint": "l", "staleness_s": 10, "tags": [
        {"ref": "t", "samples": [{"value": 1, "timestamp": _iso(NOW - timedelta(seconds=60))}]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    assert "stale" in out["worst_tags"][0]["flags"]
    assert out["worst_tags"][0]["staleness_s"] == 10


@pytest.mark.unit
def test_tag_gap_threshold_s_overrides_factor():
    base = NOW - timedelta(minutes=5)
    samples = [
        {"value": 1, "timestamp": _iso(base)},
        {"value": 2, "timestamp": _iso(base + timedelta(seconds=40))},  # 40s gap
    ]
    feeds = [{"endpoint": "l", "tags": [
        {"ref": "g", "staleness_s": 600, "gap_threshold_s": 20, "samples": samples}]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    assert "gappy" in out["worst_tags"][0]["flags"]
    assert out["worst_tags"][0]["gap_threshold_s"] == 20


# ─── flatline / heartbeat as first-class scored dimensions ───────────────────


@pytest.mark.unit
def test_liveness_section_surfaces_dead_heartbeat_and_flatline():
    feeds = [{"endpoint": "l", "tags": [
        {"ref": "hb", "heartbeat": True, "samples": [5, 5, 5, 5]},
        {"ref": "flat", "samples": [9, 9, 9, 9]},
    ]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    live = out["liveness"]
    assert live["dead_heartbeat_count"] == 1
    assert live["flatline_count"] == 1
    assert any(e["ref"] == "hb" for e in live["dead_heartbeats"])
    assert any(e["ref"] == "flat" for e in live["flatlines"])


@pytest.mark.unit
def test_flatline_after_s_threshold_uses_longest_stall():
    base = NOW - timedelta(minutes=10)
    # Value moves overall, but stalls 120s in the middle → flatline beyond a 60s budget.
    samples = [
        {"value": 1, "timestamp": _iso(base)},
        {"value": 1, "timestamp": _iso(base + timedelta(seconds=120))},
        {"value": 2, "timestamp": _iso(base + timedelta(seconds=121))},
    ]
    feeds = [{"endpoint": "l", "tags": [
        {"ref": "stuck", "flatline_after_s": 60, "staleness_s": 9000, "samples": samples}]}]
    out = dq.data_quality_scorecard(feeds, now=_iso(NOW))
    tag = out["worst_tags"][0]
    assert "flatline" in tag["flags"]
    assert tag["longest_stall_s"] == 120.0


# ─── cross-endpoint fleet rollup ─────────────────────────────────────────────


@pytest.mark.unit
def test_fleet_rollup_empty_feeds_error():
    assert "error" in dq.data_quality_fleet_rollup([])


@pytest.mark.unit
def test_fleet_rollup_ranks_by_worst_tag_and_aggregates_bad_quality():
    feeds = [
        {"endpoint": "good", "tags": [{"ref": "a", "samples": [1, 2, 3, 4]}]},
        {"endpoint": "bad", "tags": [
            {"ref": "b1", "samples": [{"value": None, "good": False} for _ in range(4)]},
            {"ref": "b2", "samples": [{"value": 1, "good": False}, {"value": 2, "good": True},
                                      {"value": 3, "good": True}, {"value": 4, "good": True}]},
        ]},
    ]
    out = dq.data_quality_fleet_rollup(feeds, now=_iso(NOW))
    assert out["endpoints_ranked_by_worst_tag"][0]["endpoint"] == "bad"
    bq = out["bad_quality_rollup"]
    assert bq["total_bad_quality_tags"] == 2  # one fully-bad + one partially-bad
    assert bq["endpoints_affected"] == 1
    assert bq["by_endpoint"][0]["endpoint"] == "bad"
    assert bq["by_endpoint"][0]["fully_bad"] == 1
    assert bq["by_endpoint"][0]["partial_bad"] == 1
    assert out["liveness_rollup"]["dead_heartbeat_count"] == 0
