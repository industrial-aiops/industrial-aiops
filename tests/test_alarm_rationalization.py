"""ISA-18.2 alarm-rationalization deepening tests (advisory, pure).

Covers the load-profile rate bands / peak period / trend, the suppression &
shelving *advice* (deadband/on-off-delay for chatter, time-limited shelve for
standing alarms — all advisory, never executed), the per-episode first-out root,
and that the deepened ``alarm_flood_report`` / ``alarm_flood_analysis`` surface
carry those sections. No live systems; no new MCP tools.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import alarm_flood as flood

T0 = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _evt(offset_s: float, source: str = "A", state: str = "ACTIVE") -> dict:
    return {"source": source, "timestamp": _iso(T0 + timedelta(seconds=offset_s)), "state": state}


def _burst(n: int, start_s: float, gap_s: float = 1.0, source: str = "FIC101") -> list[dict]:
    return [_evt(start_s + i * gap_s, source) for i in range(n)]


def _cycles(n: int, source: str, period_s: float = 10.0, start_s: float = 0.0) -> list[dict]:
    out: list[dict] = []
    for i in range(n):
        base = start_s + i * period_s
        out.append(_evt(base, source, "ACTIVE"))
        out.append(_evt(base + period_s / 2, source, "CLEARED"))
    return out


# ─── classify_alarm_rate ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rate", "band"),
    [
        (0.0, "acceptable"),
        (1.0, "acceptable"),
        (1.5, "manageable"),
        (2.0, "manageable"),
        (2.1, "over_target"),
        (9.9, "over_target"),
        (10.0, "flood"),
        (60.0, "flood"),
    ],
)
def test_classify_alarm_rate_bands(rate, band):
    assert flood.classify_alarm_rate(rate) == band


# ─── alarm_load_profile ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_load_profile_healthy_stream_all_acceptable():
    # 1 alarm every 10 minutes for 2 hours — ISA-18.2 steady state.
    events = [_evt(i * 600, f"S{i % 3}") for i in range(13)]
    prof = flood.alarm_load_profile(events)
    assert prof["insufficient_data"] is False
    assert prof["bucket_count"] == 13
    assert prof["peak_bucket"]["band"] == "acceptable"
    assert prof["band_distribution"] == {"acceptable": 13}
    assert prof["trend"] == "flat"


@pytest.mark.unit
def test_load_profile_flags_flood_peak_bucket_and_falling_trend():
    events = _burst(200, 0, gap_s=2.0) + [_evt(7200, "Z")]
    prof = flood.alarm_load_profile(events)
    assert prof["peak_bucket"]["count"] == 200
    assert prof["peak_bucket"]["band"] == "flood"
    assert prof["overall_band"] == "flood"
    assert prof["band_distribution"]["flood"] == 1
    assert prof["trend"] == "falling"  # 200 up front, quiet after


@pytest.mark.unit
def test_load_profile_detects_rising_trend():
    events = [_evt(0, "A")] + _burst(30, 3600, gap_s=2.0, source="B")
    prof = flood.alarm_load_profile(events)
    assert prof["trend"] == "rising"


@pytest.mark.unit
def test_load_profile_insufficient_data_and_validates():
    assert flood.alarm_load_profile([])["insufficient_data"] is True
    assert flood.alarm_load_profile([_evt(0)])["insufficient_data"] is True
    with pytest.raises(ValueError):
        flood.alarm_load_profile([_evt(0), _evt(600)], bucket_s=0)


@pytest.mark.unit
def test_load_profile_bounds_busiest_buckets():
    events = [_evt(i * 600, f"S{i}") for i in range(20)]
    prof = flood.alarm_load_profile(events, max_buckets=5)
    assert prof["bucket_count"] == 20
    assert len(prof["busiest_buckets"]) == 5
    assert prof["buckets_truncated"] is True
    # empty buckets fold into the acceptable band count
    assert prof["band_distribution"]["acceptable"] == 20


# ─── suppression_advice (ADVISORY ONLY) ──────────────────────────────────────


@pytest.mark.unit
def test_suppression_advice_for_chattering_derives_delays():
    events = _cycles(6, "LT200", period_s=10)  # 5s active, 10s cycle period
    advice = flood.suppression_advice(events, min_cycles=3, chatter_window_s=60)
    assert len(advice) == 1
    row = advice[0]
    assert row.source == "LT200"
    assert row.kind == "chattering"
    assert row.suggested_on_delay_s == pytest.approx(5.0)
    assert row.suggested_off_delay_s == pytest.approx(10.0)
    assert row.suggested_shelve_max_s is None
    assert "delay" in row.technique.lower()
    assert row.advisory == flood.ADVISORY_NOTE


@pytest.mark.unit
def test_suppression_advice_for_standing_suggests_time_limited_shelve():
    events = [_evt(0, "TI400", "ACTIVE")]
    now = T0 + timedelta(days=2)
    advice = flood.suppression_advice(events, now=now, stale_after_s=86400)
    assert len(advice) == 1
    row = advice[0]
    assert row.kind == "standing"
    assert row.suggested_shelve_max_s == pytest.approx(flood.DEFAULT_MAX_SHELVE_S)
    assert row.suggested_on_delay_s is None
    assert "shelve" in row.technique.lower()
    assert "48.0h" in row.basis or "48h" in row.basis


@pytest.mark.unit
def test_suppression_advice_chattering_first_then_standing_no_dup():
    # LT200 chatters; TI400 stands. Chattering ranks first; no source duplicated.
    events = (
        _cycles(6, "LT200", period_s=10)
        + [_evt(0, "TI400", "ACTIVE")]
        + [_evt(50, "LT200", "ACTIVE")]  # keep LT200 active at the end too
    )
    now = T0 + timedelta(days=2)
    advice = flood.suppression_advice(events, now=now, stale_after_s=86400)
    kinds = [r.kind for r in advice]
    sources = [r.source for r in advice]
    assert kinds[0] == "chattering"
    assert "standing" in kinds
    assert sources.count("LT200") == 1  # not advised twice


@pytest.mark.unit
def test_suppression_advice_empty_bounded_and_validates():
    assert flood.suppression_advice([]) == []
    many = []
    for k in range(10):
        many += _cycles(6, f"C{k}", period_s=10, start_s=k * 1000)
    assert len(flood.suppression_advice(many, max_rows=3)) == 3
    with pytest.raises(ValueError):
        flood.suppression_advice([_evt(0)], now="not-a-time")


@pytest.mark.unit
def test_advice_as_dicts_shape_and_advisory_present():
    events = _cycles(6, "LT200", period_s=10)
    dicts = flood.advice_as_dicts(flood.suppression_advice(events))
    assert dicts
    row = dicts[0]
    assert set(row) == {
        "source",
        "kind",
        "technique",
        "suggested_on_delay_s",
        "suggested_off_delay_s",
        "suggested_shelve_max_s",
        "basis",
        "advisory",
    }
    assert "ADVISORY ONLY" in row["advisory"]
    assert "never" in row["advisory"].lower()


# ─── first-out per flood episode (root-cause grouping) ───────────────────────


@pytest.mark.unit
def test_flood_episode_reports_first_out_annunciation():
    events = [_evt(0, "PT101")] + _burst(20, 1, source="FIC101")
    eps = flood.detect_floods(events, window_s=600, threshold=10)
    assert len(eps) == 1
    assert eps[0].first_out == {"source": "PT101", "ts": _iso(T0)}


# ─── deepened report / tool surface ──────────────────────────────────────────


@pytest.mark.unit
def test_report_carries_load_profile_advice_and_first_out():
    events = _cycles(6, "LT200", period_s=10) + _burst(30, 700) + [_evt(0, "TI400", "ACTIVE")]
    now = T0 + timedelta(days=2)
    out = flood.alarm_flood_report(events, now=now, stale_after_s=86400)
    assert out["load_profile"]["insufficient_data"] is False
    assert out["advisory_note"] == flood.ADVISORY_NOTE
    assert "suppression_advice" in out["truncated"]
    kinds = {r["kind"] for r in out["suppression_advice"]}
    assert {"chattering", "standing"} <= kinds
    assert out["flood_episodes"][0]["first_out"]["source"] == "FIC101"


@pytest.mark.unit
def test_report_load_bucket_s_is_threaded():
    events = _burst(30, 0, gap_s=2.0) + [_evt(600, "Z")]
    out = flood.alarm_flood_report(events, load_bucket_s=60.0)
    assert out["load_profile"]["bucket_s"] == 60.0


def _tool_fn(name: str):
    from mcp_server import _shared
    from mcp_server.server import register_profile

    register_profile("all")
    return _shared.mcp._tool_manager._tools[name].fn


@pytest.mark.unit
def test_alarm_flood_analysis_tool_exposes_advice_and_load_profile():
    fn = _tool_fn("alarm_flood_analysis")
    events = _cycles(6, "LT200", period_s=10) + _burst(30, 700)
    out = fn(events=events, load_bucket_s=300.0)
    assert out["load_profile"]["bucket_s"] == 300.0
    assert any(r["kind"] == "chattering" for r in out["suppression_advice"])
    assert out["advisory_note"] == flood.ADVISORY_NOTE
    assert "collected" not in out
