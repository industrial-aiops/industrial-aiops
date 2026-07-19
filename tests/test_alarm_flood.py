"""ISA-18.2 alarm-flood deepening tests over synthetic event streams.

Covers flood-episode boundary detection, chattering cycle counting, stale /
standing alarms, the honest insufficient-data paths of flood_summary, the
rationalization worksheet (rows + CSV shape via the MCP tool), and that the
new MCP tools are governed and output-bounded. No live systems.
"""

from __future__ import annotations

import csv
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


# ─── detect_floods ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_detect_floods_finds_one_episode_with_boundaries():
    # 20 alarms in 20s (>= 10/600s) then silence: one episode.
    events = _burst(20, 0)
    eps = flood.detect_floods(events, window_s=600, threshold=10)
    assert len(eps) == 1
    ep = eps[0]
    assert ep.start == _iso(T0)
    assert ep.end == _iso(T0 + timedelta(seconds=19))
    assert ep.count == 20
    assert ep.peak_count_in_window == 20
    assert ep.top_contributors[0]["source"] == "FIC101"


@pytest.mark.unit
def test_detect_floods_below_threshold_is_empty():
    assert flood.detect_floods(_burst(9, 0), window_s=600, threshold=10) == []


@pytest.mark.unit
def test_detect_floods_two_separated_episodes():
    # Two 15-alarm bursts separated by well over a window of silence.
    events = _burst(15, 0) + _burst(15, 2000)
    eps = flood.detect_floods(events, window_s=600, threshold=10)
    assert len(eps) == 2
    assert eps[0].end < eps[1].start


@pytest.mark.unit
def test_detect_floods_peak_rate_normalized_to_10min():
    eps = flood.detect_floods(_burst(30, 0), window_s=300, threshold=10)
    assert len(eps) == 1
    # 30 alarms peak in a 300s window → 60 per 10 min.
    assert eps[0].peak_rate_per_10min == pytest.approx(60.0)


@pytest.mark.unit
def test_detect_floods_ignores_cleared_events():
    # 20 CLEARED transitions are not annunciations — no flood.
    events = [_evt(i, state="CLEARED") for i in range(20)]
    assert flood.detect_floods(events, window_s=600, threshold=10) == []


@pytest.mark.unit
def test_detect_floods_caps_episodes():
    events: list[dict] = []
    for k in range(4):
        events += _burst(12, k * 5000, source=f"S{k}")
    eps = flood.detect_floods(events, window_s=600, threshold=10, max_episodes=2)
    assert len(eps) == 2


@pytest.mark.unit
def test_detect_floods_validates_params():
    with pytest.raises(ValueError):
        flood.detect_floods([], window_s=0)
    with pytest.raises(ValueError):
        flood.detect_floods([], threshold=0)


@pytest.mark.unit
def test_detect_floods_empty_and_untimed_events():
    assert flood.detect_floods([]) == []
    assert flood.detect_floods([{"source": "A", "timestamp": None}]) == []


# ─── chattering_alarms ───────────────────────────────────────────────────────


def _cycles(n: int, source: str, period_s: float = 10.0, start_s: float = 0.0) -> list[dict]:
    """n full ACTIVE→CLEARED cycles for one source."""
    out: list[dict] = []
    for i in range(n):
        base = start_s + i * period_s
        out.append(_evt(base, source, "ACTIVE"))
        out.append(_evt(base + period_s / 2, source, "CLEARED"))
    return out


@pytest.mark.unit
def test_chattering_detected_and_cycle_count():
    events = _cycles(6, "LT200", period_s=10)  # 6 cycles in ~55s
    out = flood.chattering_alarms(events, min_cycles=3, window_s=60)
    assert len(out) == 1
    c = out[0]
    assert c.source == "LT200"
    assert c.cycles == 6
    assert c.max_cycles_in_window >= 3
    assert c.cycles_per_hour > 0


@pytest.mark.unit
def test_chattering_slow_cycles_not_flagged():
    # 6 cycles but spread over an hour — never 3 completions inside 60s.
    events = _cycles(6, "PT300", period_s=600)
    assert flood.chattering_alarms(events, min_cycles=3, window_s=60) == []


@pytest.mark.unit
def test_chattering_requires_full_cycles():
    # Repeated ACTIVE with no CLEARED = re-annunciation, not chattering cycles.
    events = [_evt(i, "X", "ACTIVE") for i in range(10)]
    assert flood.chattering_alarms(events) == []


@pytest.mark.unit
def test_chattering_sorted_worst_first_and_validates():
    events = _cycles(3, "MILD", period_s=15) + _cycles(8, "BAD", period_s=5, start_s=100)
    out = flood.chattering_alarms(events, min_cycles=3, window_s=60)
    assert [c.source for c in out][0] == "BAD"
    with pytest.raises(ValueError):
        flood.chattering_alarms(events, min_cycles=0)


# ─── stale_standing_alarms ───────────────────────────────────────────────────


@pytest.mark.unit
def test_stale_alarm_detected_beyond_threshold():
    events = [_evt(0, "TI400", "ACTIVE")]
    now = T0 + timedelta(days=2)
    out = flood.stale_standing_alarms(events, now, stale_after_s=86400)
    assert len(out) == 1
    assert out[0].source == "TI400"
    assert out[0].active_since == _iso(T0)
    assert out[0].active_for_s == pytest.approx(2 * 86400)


@pytest.mark.unit
def test_stale_alarm_cleared_not_flagged():
    events = [_evt(0, "TI400", "ACTIVE"), _evt(100, "TI400", "CLEARED")]
    assert flood.stale_standing_alarms(events, T0 + timedelta(days=2)) == []


@pytest.mark.unit
def test_stale_keeps_original_activation_across_reannunciation():
    # Still active; re-annunciated later — age counts from the FIRST activation.
    events = [_evt(0, "TI400", "ACTIVE"), _evt(3600, "TI400", "ACTIVE")]
    out = flood.stale_standing_alarms(events, T0 + timedelta(days=2), stale_after_s=86400)
    assert out and out[0].active_since == _iso(T0)


@pytest.mark.unit
def test_stale_within_threshold_not_flagged_and_validates():
    events = [_evt(0, "TI400", "ACTIVE")]
    assert flood.stale_standing_alarms(events, T0 + timedelta(hours=1)) == []
    with pytest.raises(ValueError):
        flood.stale_standing_alarms(events, "not-a-time")
    with pytest.raises(ValueError):
        flood.stale_standing_alarms(events, T0, stale_after_s=0)


# ─── flood_summary ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_flood_summary_insufficient_data_paths():
    assert flood.flood_summary([])["insufficient_data"] is True
    assert flood.flood_summary([_evt(0)])["insufficient_data"] is True
    # Two events 30s apart: span shorter than one 600s window.
    short = flood.flood_summary([_evt(0), _evt(30)])
    assert short["insufficient_data"] is True
    assert "window" in short["reason"]


@pytest.mark.unit
def test_flood_summary_healthy_stream_meets_targets():
    # 1 alarm every 10 minutes for 2 hours — the ISA-18.2 steady-state target.
    events = [_evt(i * 600, f"S{i % 3}") for i in range(13)]
    out = flood.flood_summary(events)
    assert out["insufficient_data"] is False
    assert out["flood_episodes"] == 0
    assert out["percent_time_in_flood"] == 0.0
    assert out["avg_alarms_per_10min"] <= 2.0
    assert out["meets_avg_target"] is True
    assert out["meets_flood_time_target"] is True


@pytest.mark.unit
def test_flood_summary_flooded_stream_fails_targets():
    # A 200-alarm burst inside an otherwise long span.
    events = _burst(200, 0, gap_s=2.0) + [_evt(7200, "Z")]
    out = flood.flood_summary(events)
    assert out["insufficient_data"] is False
    assert out["flood_episodes"] >= 1
    assert out["percent_time_in_flood"] > flood.TARGET_FLOOD_TIME_PCT
    assert out["peak_alarms_per_10min"] > flood.FLOOD_THRESHOLD
    assert out["meets_flood_time_target"] is False


# ─── rationalization_worksheet ───────────────────────────────────────────────


@pytest.mark.unit
def test_worksheet_rows_shape_and_flags():
    events = _burst(50, 0) + _cycles(6, "LT200", period_s=10, start_s=700) + [_evt(1200, "PT1")]
    rows = flood.rationalization_worksheet(events)
    assert rows[0].alarm_id == "FIC101"  # count-descending
    assert rows[0].in_flood is True
    total = sum(r.count for r in rows)
    assert total == 50 + 6 + 1
    assert sum(r.pct_of_total for r in rows) == pytest.approx(100.0, abs=0.5)
    lt = next(r for r in rows if r.alarm_id == "LT200")
    assert lt.chattering is True
    assert "chattering" in lt.recommendation
    pt = next(r for r in rows if r.alarm_id == "PT1")
    assert pt.recommendation.startswith("Retain")


@pytest.mark.unit
def test_worksheet_empty_and_capped():
    assert flood.rationalization_worksheet([]) == []
    events = [_evt(i * 30, f"S{i}") for i in range(20)]
    assert len(flood.rationalization_worksheet(events, max_rows=5)) == 5


@pytest.mark.unit
def test_worksheet_rows_as_dicts_match_columns():
    rows = flood.rationalization_worksheet(_burst(12, 0))
    dicts = flood.worksheet_rows_as_dicts(rows)
    assert dicts and tuple(dicts[0]) == flood.WORKSHEET_COLUMNS


# ─── alarm_flood_report (combined, bounded) ──────────────────────────────────


@pytest.mark.unit
def test_report_bounded_with_truncation_flags():
    events: list[dict] = []
    for k in range(30):
        events += _burst(12, k * 5000, source=f"S{k}")
    out = flood.alarm_flood_report(events, max_episodes=3, max_rows=5)
    assert len(out["flood_episodes"]) == 3
    assert out["truncated"]["flood_episodes"] is True
    assert len(out["worksheet_preview"]) <= 5
    assert out["truncated"]["worksheet"] is True
    assert out["summary"]["insufficient_data"] is False


@pytest.mark.unit
def test_report_no_events_is_error():
    assert "error" in flood.alarm_flood_report([])


# ─── MCP tools: governed, injected events, CSV, bounded ──────────────────────


def _tool_fn(name: str):
    from mcp_server import _shared
    from mcp_server.server import register_profile

    register_profile("all")
    return _shared.mcp._tool_manager._tools[name].fn


@pytest.mark.unit
def test_alarm_tools_are_governed():
    for name in ("alarm_flood_analysis", "alarm_rationalization_worksheet"):
        fn = _tool_fn(name)
        assert getattr(fn, "_is_governed_tool", False), f"{name} not governed"


@pytest.mark.unit
def test_alarm_flood_analysis_tool_with_injected_events():
    fn = _tool_fn("alarm_flood_analysis")
    out = fn(events=_burst(200, 0, gap_s=2.0) + [_evt(7200, "Z")], max_episodes=2)
    assert out["summary"]["flood_episodes"] >= 1
    assert len(out["flood_episodes"]) <= 2
    assert "collected" not in out  # injected events skip live collection


@pytest.mark.unit
def test_alarm_flood_analysis_tool_error_shape():
    fn = _tool_fn("alarm_flood_analysis")
    out = fn(events=_burst(2, 0), window_s=0)  # invalid → canonical {error, hint}
    assert set(out) >= {"error", "hint"}
    # Empty events → the brain's honest error dict (no exception path needed).
    assert "error" in fn(events=[])


@pytest.mark.unit
def test_worksheet_tool_inline_rows_bounded():
    fn = _tool_fn("alarm_rationalization_worksheet")
    events = [_evt(i * 30, f"S{i % 60}") for i in range(120)]
    out = fn(events=events)
    assert out["row_count"] == 60
    assert len(out["rows"]) == 50
    assert out["truncated"] is True
    assert out["columns"] == list(flood.WORKSHEET_COLUMNS)


@pytest.mark.unit
def test_worksheet_tool_writes_csv(tmp_path):
    fn = _tool_fn("alarm_rationalization_worksheet")
    dest = tmp_path / "worksheet.csv"
    out = fn(events=_burst(12, 0) + [_evt(100, "PT1")], out_path=str(dest))
    assert out["csv_path"] == str(dest)
    with dest.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == out["row_count"] == 2
    assert tuple(rows[0]) == flood.WORKSHEET_COLUMNS
    assert rows[0]["alarm_id"] == "FIC101"


@pytest.mark.unit
def test_worksheet_tool_creates_a_missing_parent_dir(tmp_path):
    """A missing parent is CREATED (0700), not rejected — deliberate change.

    This tool used to raise on a missing parent while the repo's other two
    ``out_path`` tools (``compliance_report``, the evidence zip export) created
    it, because this one did its own ad-hoc check instead of calling the shared
    ``validate_output_path``. Routing it through the shared guard — which is what
    added traversal and suffix rejection here — also made the three consistent.
    Consistency is the point: three tools taking the same argument should not
    answer the same input three different ways.
    """
    fn = _tool_fn("alarm_rationalization_worksheet")
    target = tmp_path / "nope" / "w.csv"
    out = fn(events=_burst(12, 0), out_path=str(target))
    assert "error" not in out, out
    assert target.exists()
    assert (target.parent.stat().st_mode & 0o777) == 0o700


@pytest.mark.unit
def test_worksheet_tool_rejects_traversal(tmp_path):
    """The guard that the shared validator brought with it."""
    fn = _tool_fn("alarm_rationalization_worksheet")
    out = fn(events=_burst(12, 0), out_path=str(tmp_path / ".." / "escaped.csv"))
    assert "error" in out


# ─── live collection path (same acquisition path as the RCA copilot) ─────────


@pytest.mark.unit
def test_live_collection_diffs_snapshots_into_transitions(monkeypatch):
    from mcp_server.tools import alarm_tools

    snapshots = iter(
        [
            [{"source": "A", "state": "ACTIVE"}],
            [{"source": "A", "state": "ACTIVE"}, {"source": "B", "state": "ACTIVE"}],
            [{"source": "B", "state": "ACTIVE"}],
        ]
    )
    monkeypatch.setattr(alarm_tools, "collect_active_alarms", lambda target: next(snapshots, []))
    monkeypatch.setattr(alarm_tools.time, "sleep", lambda s: None)
    clock = iter([0.0, 0.0, 0.5, 1.0, 1.5])
    monkeypatch.setattr(alarm_tools.time, "monotonic", lambda: next(clock, 99.0))
    events = alarm_tools._collect_transition_events(object(), duration_s=2)
    states = [(e["source"], e["state"]) for e in events]
    assert ("A", "ACTIVE") in states
    assert ("B", "ACTIVE") in states
    assert ("A", "CLEARED") in states


# ─── CLI commands ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cli_alarm_flood_and_worksheet(tmp_path):
    import json

    from typer.testing import CliRunner

    from iaiops.cli import app

    events_file = tmp_path / "events.json"
    events_file.write_text(json.dumps(_burst(200, 0, gap_s=2.0) + [_evt(7200, "Z")]))
    runner = CliRunner()
    res = runner.invoke(app, ["diag", "alarm-flood", "--input", str(events_file)])
    assert res.exit_code == 0
    assert "flood_episodes" in res.output

    out_csv = tmp_path / "w.csv"
    res = runner.invoke(
        app, ["diag", "alarm-worksheet", "--input", str(events_file), "--out", str(out_csv)]
    )
    assert res.exit_code == 0
    assert out_csv.exists()
    header = out_csv.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(flood.WORKSHEET_COLUMNS)
