"""Conservative baseline learning (A6) — change-log baseline, NOT anomaly detection.

Covers: learning happy path + explicit refusals (too few samples / short span),
change-point segmentation, conservative violation logic (single spike NOT
flagged; sustained excursion flagged WITH citations), store roundtrip +
permissions, and the governed/bounded MCP tool surface.
"""

from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import baseline as bl
from iaiops.core.brain import baseline_store as bls

BASE = datetime(2026, 6, 1, tzinfo=UTC)


def _samples(
    n: int,
    values: list[float] | None = None,
    step_s: float = 1800.0,
    start: datetime = BASE,
    quality: str = "GOOD",
    tag: str = "line1.temp",
) -> list[dict]:
    """n rows in local-store shape, 30 min apart by default (n=100 → ~50h span)."""
    out = []
    for i in range(n):
        value = values[i % len(values)] if values else 50.0 + (i % 3) - 1  # 49/50/51
        out.append(
            {
                "ts": (start + timedelta(seconds=i * step_s)).isoformat(),
                "endpoint": "plc1",
                "protocol": "modbus",
                "tag": tag,
                "value": value,
                "quality": quality,
                "unit": "C",
            }
        )
    return out


def _learned(n: int = 120, **kwargs) -> dict:
    result = bl.learn_baseline(_samples(n, **kwargs), "line1.temp")
    assert result["status"] == "ok"
    return result


# ─── learning: happy path + refusals ─────────────────────────────────────────


@pytest.mark.unit
def test_learn_happy_path_robust_band_with_window_citation():
    result = _learned(120)
    band = result["band"]
    assert band["median"] == pytest.approx(50.0)
    assert band["mad"] == pytest.approx(1.0)
    assert 49.0 <= band["p1"] <= 50.0
    assert 50.0 <= band["p99"] <= 51.0
    assert result["n_samples"] == 120
    window = result["window"]
    assert window["from_ts"] == BASE.isoformat()
    assert window["span_s"] >= bl.DEFAULT_MIN_SPAN_S


@pytest.mark.unit
def test_learn_refuses_too_few_samples_with_explicit_missing():
    result = bl.learn_baseline(_samples(30), "line1.temp")
    assert result["status"] == "insufficient_data"
    assert result["n_samples"] == 30
    assert any("70 more required" in m for m in result["missing"])
    assert "band" not in result  # it never invents a band


@pytest.mark.unit
def test_learn_refuses_short_span_even_with_many_samples():
    # 200 samples but only ~200s of history — span refusal.
    result = bl.learn_baseline(_samples(200, step_s=1.0), "line1.temp")
    assert result["status"] == "insufficient_data"
    assert any("history span" in m for m in result["missing"])


@pytest.mark.unit
def test_learn_excludes_bad_quality_and_foreign_tags():
    rows = _samples(120) + _samples(50, values=[999.0], quality="BAD")
    rows += _samples(50, values=[999.0], tag="other.tag")
    result = bl.learn_baseline(rows, "line1.temp")
    assert result["status"] == "ok"
    assert result["n_samples"] == 120
    assert result["skipped_samples"] == 100
    assert result["band"]["p99"] < 100  # the 999s never leaked into the band


@pytest.mark.unit
def test_learn_requires_tag_and_list_input():
    with pytest.raises(ValueError, match="tag is required"):
        bl.learn_baseline(_samples(5), "")
    with pytest.raises(ValueError, match="must be a list"):
        bl.learn_baseline({"ts": "x"}, "line1.temp")  # type: ignore[arg-type]


# ─── change-point segmentation ────────────────────────────────────────────────


@pytest.mark.unit
def test_learn_segments_at_latest_recorded_change():
    before = _samples(120, values=[30.0, 30.5, 31.0])
    change_ts = BASE + timedelta(days=4)
    after = _samples(120, values=[69.0, 70.0, 71.0], start=change_ts + timedelta(hours=1))
    changes = [
        {"ts": BASE.isoformat(), "note": "commissioned"},
        {"ts": change_ts.isoformat(), "note": "setpoint 30→70C"},
    ]
    result = bl.learn_baseline(before + after, "line1.temp", changes=changes)
    assert result["status"] == "ok"
    assert result["n_samples"] == 120  # pre-change regime excluded entirely
    assert result["segment"]["segmented"] is True
    assert result["segment"]["after_change_ts"] == change_ts.isoformat()
    assert result["segment"]["samples_before_change_excluded"] == 120
    assert result["band"]["median"] == pytest.approx(70.0)


@pytest.mark.unit
def test_learn_refuses_when_post_change_segment_is_thin():
    rows = _samples(300)
    late_change = {"ts": (BASE + timedelta(days=6)).isoformat(), "note": "probe swap"}
    result = bl.learn_baseline(rows, "line1.temp", changes=[late_change])
    assert result["status"] == "insufficient_data"
    assert result["segment"]["segmented"] is True


# ─── conservative violation logic ─────────────────────────────────────────────


@pytest.mark.unit
def test_single_spike_is_not_flagged():
    baseline = _learned()
    fresh = _samples(10, start=BASE + timedelta(days=10))
    fresh[4]["value"] = 500.0  # one wild spike, way beyond the band
    result = bl.check_against_baseline(fresh, baseline)
    assert result["status"] == "ok"
    assert result["violations"] == []


@pytest.mark.unit
def test_two_consecutive_outliers_still_not_flagged_below_sustain_n():
    baseline = _learned()
    fresh = _samples(10, start=BASE + timedelta(days=10))
    fresh[3]["value"] = fresh[4]["value"] = 500.0  # 2 < sustain_n=3
    result = bl.check_against_baseline(fresh, baseline)
    assert result["status"] == "ok"


@pytest.mark.unit
def test_within_band_excursion_not_flagged_without_mad_margin():
    baseline = _learned()  # p99≈51, mad=1 → threshold high≈54
    fresh = _samples(10, values=[53.0], start=BASE + timedelta(days=10))
    result = bl.check_against_baseline(fresh, baseline)
    assert result["status"] == "ok"  # beyond p99 but within the 3×MAD margin


@pytest.mark.unit
def test_sustained_excursion_flagged_with_full_citation():
    baseline = _learned()
    fresh = _samples(10, start=BASE + timedelta(days=10))
    for i in (5, 6, 7, 8):
        fresh[i]["value"] = 90.0
    result = bl.check_against_baseline(fresh, baseline)
    assert result["status"] == "violation"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["direction"] == "above"
    assert v["consecutive_samples"] == 4
    assert v["from_ts"] == fresh[5]["ts"]
    assert v["to_ts"] == fresh[8]["ts"]
    assert [s["value"] for s in v["samples"]] == [90.0] * 4
    # every flag cites its baseline: window + sample count + band values
    cite = v["baseline"]
    assert cite["window_from"] == baseline["window"]["from_ts"]
    assert cite["window_to"] == baseline["window"]["to_ts"]
    assert cite["n_samples"] == baseline["n_samples"]
    assert cite["band"] == {
        k: pytest.approx(baseline["band"][k]) for k in ("p1", "p99", "median", "mad")
    }


@pytest.mark.unit
def test_sustained_low_excursion_flagged_below():
    baseline = _learned()
    fresh = _samples(8, values=[10.0], start=BASE + timedelta(days=10))
    result = bl.check_against_baseline(fresh, baseline)
    assert result["status"] == "violation"
    assert result["violations"][0]["direction"] == "below"


@pytest.mark.unit
def test_check_refuses_insufficient_baseline():
    refused = bl.learn_baseline(_samples(5), "line1.temp")
    with pytest.raises(ValueError, match="insufficient_data"):
        bl.check_against_baseline(_samples(5), refused)


@pytest.mark.unit
def test_check_output_is_bounded():
    baseline = _learned()
    # 30 separate 3-sample excursions (separated by in-band samples).
    fresh: list[dict] = []
    start = BASE + timedelta(days=10)
    for burst in range(30):
        fresh += _samples(3, values=[90.0], step_s=60.0, start=start + timedelta(hours=burst))
        fresh += _samples(1, values=[50.0], start=start + timedelta(hours=burst, minutes=30))
    result = bl.check_against_baseline(fresh, baseline)
    assert result["status"] == "violation"
    assert len(result["violations"]) == bl.MAX_VIOLATIONS
    assert result["violations_truncated"] is True


# ─── status classification (never guesses) ────────────────────────────────────


@pytest.mark.unit
def test_classify_status_vocabulary():
    assert bl.classify_status(None) == "no_baseline"
    assert bl.classify_status({"changes": []}) == "no_baseline"
    assert bl.classify_status({"last_learn": {"status": "insufficient_data"}}) == "learning"
    ok = {"baseline": {"status": "ok"}, "last_check": None}
    assert bl.classify_status(ok) == "ok"
    bad = {"baseline": {"status": "ok"}, "last_check": {"status": "violation"}}
    assert bl.classify_status(bad) == "violation"


# ─── store: roundtrip + permissions + change log ──────────────────────────────


@pytest.mark.unit
def test_store_roundtrip_and_owner_only_permissions(tmp_path):
    result = bls.record_change("line1.temp", "2026-06-05T00:00:00", "probe swap", base_dir=tmp_path)
    assert result["change"]["note"] == "probe swap"
    path = bls.store_path(tmp_path)
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store = bls.load_store(tmp_path)
    assert store["tags"]["line1.temp"]["changes"][0]["note"] == "probe swap"


@pytest.mark.unit
def test_store_missing_file_is_empty_not_error(tmp_path):
    assert bls.load_store(tmp_path) == {"version": 1, "tags": {}}


@pytest.mark.unit
def test_store_corrupt_file_fails_with_teaching_error(tmp_path):
    bls.store_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    bls.store_path(tmp_path).write_text("{not json", "utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        bls.load_store(tmp_path)


@pytest.mark.unit
def test_record_change_requires_note_and_valid_ts(tmp_path):
    with pytest.raises(ValueError, match="note is required"):
        bls.record_change("line1.temp", None, "  ", base_dir=tmp_path)
    with pytest.raises(ValueError, match="ISO-8601"):
        bls.record_change("line1.temp", "yesterday-ish", "x", base_dir=tmp_path)


@pytest.mark.unit
def test_record_change_log_is_bounded(tmp_path):
    for i in range(bls.MAX_CHANGES_PER_TAG + 10):
        bls.record_change("t", f"2026-06-01T00:{i % 60:02d}:00", f"change {i}", base_dir=tmp_path)
    record = bls.load_store(tmp_path)["tags"]["t"]
    assert len(record["changes"]) == bls.MAX_CHANGES_PER_TAG
    assert record["changes"][-1]["note"] == f"change {bls.MAX_CHANGES_PER_TAG + 9}"


# ─── flows over the local SQLite store ────────────────────────────────────────


def _seed_db(tmp_path, rows: list[dict]):
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    db = tmp_path / "data.db"
    sink = SQLiteLocalSink(db_path=db, endpoint="plc1", protocol="modbus")
    sink.write(
        [
            {
                "timestamp": r["ts"],
                "metric": r["tag"],
                "value": r["value"],
                "numeric": True,
                "tags": {"quality": r["quality"], "unit": r["unit"]},
            }
            for r in rows
        ]
    )
    sink.close()
    return db


@pytest.mark.integration
def test_learn_flow_persists_band_and_segments_at_change(tmp_path):
    change_ts = BASE + timedelta(days=4)
    rows = _samples(120, values=[30.0, 30.5, 31.0])
    rows += _samples(120, values=[69.0, 70.0, 71.0], start=change_ts + timedelta(hours=1))
    db = _seed_db(tmp_path, rows)
    bls.record_change("line1.temp", change_ts.isoformat(), "setpoint 30→70C", base_dir=tmp_path)
    result = bls.learn_flow("line1.temp", base_dir=tmp_path, db_path=db)
    assert result["status"] == "ok"
    assert result["band"]["median"] == pytest.approx(70.0)
    assert bls.status_flow("line1.temp", base_dir=tmp_path)["status"] == "ok"


@pytest.mark.integration
def test_check_flow_no_baseline_answer_and_violation_roundtrip(tmp_path):
    now = BASE + timedelta(days=10)
    db = _seed_db(tmp_path, _samples(240))
    no_base = bls.check_flow("line1.temp", base_dir=tmp_path, db_path=db, now=now)
    assert no_base["status"] == "no_baseline"
    assert "never guesses" in no_base["note"]

    assert bls.learn_flow("line1.temp", base_dir=tmp_path, db_path=db)["status"] == "ok"
    # a sustained excursion inside the check window
    _seed_db(tmp_path, _samples(6, values=[90.0], step_s=60.0, start=now - timedelta(minutes=30)))
    result = bls.check_flow("line1.temp", window_s=3600, base_dir=tmp_path, db_path=db, now=now)
    assert result["status"] == "violation"
    assert result["violations"][0]["baseline"]["n_samples"] == 240
    assert bls.status_flow("line1.temp", base_dir=tmp_path)["status"] == "violation"


@pytest.mark.integration
def test_learning_status_after_refused_learn(tmp_path):
    db = _seed_db(tmp_path, _samples(10))
    result = bls.learn_flow("line1.temp", base_dir=tmp_path, db_path=db)
    assert result["status"] == "insufficient_data"
    assert bls.status_flow("line1.temp", base_dir=tmp_path)["status"] == "learning"


@pytest.mark.unit
def test_status_flow_unknown_tag_and_bounded_listing(tmp_path):
    assert bls.status_flow("ghost.tag", base_dir=tmp_path)["status"] == "no_baseline"
    for i in range(bls.MAX_STATUS_TAGS + 5):
        bls.record_change(f"tag{i:03d}", "2026-06-01T00:00:00", "seed", base_dir=tmp_path)
    listing = bls.status_flow(base_dir=tmp_path)
    assert listing["tracked_tags"] == bls.MAX_STATUS_TAGS + 5
    assert listing["listed"] == bls.MAX_STATUS_TAGS
    assert listing["truncated"] is True
    assert len(listing["tags"]) == bls.MAX_STATUS_TAGS


@pytest.mark.unit
def test_check_flow_validates_window(tmp_path):
    with pytest.raises(ValueError, match="window_s"):
        bls.check_flow("line1.temp", window_s=1.0, base_dir=tmp_path)


# ─── MCP tools: governed + bounded surface ────────────────────────────────────


@pytest.mark.unit
def test_baseline_tools_are_governed_low_risk():
    import mcp_server.tools.baseline_tools as mod

    for name in ("baseline_learn", "baseline_check", "baseline_record_change", "baseline_status"):
        fn = getattr(mod, name)
        assert getattr(fn, "_is_governed_tool", False), f"{name} not governed"
        assert getattr(fn, "_risk_level", "") == "low"


@pytest.mark.unit
def test_baseline_tools_registered_on_mcp():
    import asyncio

    from mcp_server._shared import mcp
    from mcp_server.server import register_profile

    register_profile("all")
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {
        "baseline_learn",
        "baseline_check",
        "baseline_record_change",
        "baseline_status",
    } <= names


@pytest.mark.integration
def test_baseline_tools_end_to_end_via_iaiops_home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    import mcp_server.tools.baseline_tools as mod

    rows = _samples(240)
    _seed_db_at_home(tmp_path, rows)
    change = mod.baseline_record_change(tag="line1.temp", note="commissioned")
    assert change["changes_recorded"] == 1  # change predates samples? use early ts
    # re-learn: the change was recorded "now" (after all samples) — refusal expected,
    # which is exactly the honest behavior (post-change history is empty).
    refused = mod.baseline_learn(tag="line1.temp")
    assert refused["status"] == "insufficient_data"
    assert mod.baseline_status(tag="line1.temp")["status"] == "learning"


def _seed_db_at_home(home, rows):
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    sink = SQLiteLocalSink(db_path=home / "data.db", endpoint="plc1", protocol="modbus")
    sink.write(
        [
            {
                "timestamp": r["ts"],
                "metric": r["tag"],
                "value": r["value"],
                "numeric": True,
                "tags": {"quality": r["quality"], "unit": r["unit"]},
            }
            for r in rows
        ]
    )
    sink.close()


@pytest.mark.integration
def test_baseline_tool_errors_return_teaching_dict(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    import mcp_server.tools.baseline_tools as mod

    # no local store yet → FileNotFoundError translated into an error dict
    result = mod.baseline_learn(tag="line1.temp")
    assert "error" in result
    assert "No local store" in result["error"]
