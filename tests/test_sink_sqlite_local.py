"""Local SQLite sink (queryability layer) — write/read roundtrip + filters.

Everything runs against a tmp_path db (no ~/.iaiops touched): the shared
``historian_push`` path with ``sink="sqlite"``, the query layer with its
validated filters, and the audit-style file hardening.
"""

from __future__ import annotations

import stat

import pytest

from iaiops.core.sink.push import historian_push
from iaiops.core.sink.sqlite_local import (
    SampleFilter,
    SQLiteLocalSink,
    count_samples,
    latest_samples,
    query_samples,
    validate_filter,
)

POINTS = [
    {
        "ref": "line1.temp",
        "value": 21.5,
        "timestamp": "2026-07-01T00:00:00Z",
        "quality": "good",
        "unit": "C",
    },
    {
        "ref": "line1.temp",
        "value": 22.0,
        "timestamp": "2026-07-01T01:00:00Z",
        "quality": "good",
        "unit": "C",
    },
    {"ref": "line1.state", "value": "RUNNING", "timestamp": "2026-07-01T00:30:00Z"},
    {"ref": "line2.pressure", "value": 3.1, "timestamp": "2026-06-30T23:00:00Z"},
]


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "data.db"
    result = historian_push(POINTS, "sqlite", db_path=path, endpoint="plc1", protocol="modbus")
    assert "error" not in result
    return path


@pytest.mark.unit
def test_push_roundtrip_keeps_text_values(db):
    rows = query_samples(SampleFilter(), db_path=db)
    assert len(rows) == 4  # non-numeric kept (unlike the TSDB sinks)
    by_tag = {r["tag"]: r for r in rows if r["tag"] != "line1.temp"}
    assert by_tag["line1.state"]["value"] == "RUNNING"
    temp = [r for r in rows if r["tag"] == "line1.temp"]
    assert [r["value"] for r in temp] == [21.5, 22.0]
    assert temp[0]["quality"] == "good" and temp[0]["unit"] == "C"
    assert temp[0]["endpoint"] == "plc1" and temp[0]["protocol"] == "modbus"


@pytest.mark.unit
def test_push_tally_reports_no_skips_for_sqlite(tmp_path):
    result = historian_push(POINTS, "sqlite", db_path=tmp_path / "d.db")
    assert result["received"] == 4
    assert result["written"] == 4
    assert result["skipped_non_numeric"] == 0
    assert "export" in result["note"]


@pytest.mark.unit
def test_query_filters_since_until_tag_endpoint(db):
    since = query_samples(SampleFilter(since="2026-07-01T00:00:00Z"), db_path=db)
    assert {r["tag"] for r in since} == {"line1.temp", "line1.state"}
    until = query_samples(SampleFilter(until="2026-06-30T23:59:59Z"), db_path=db)
    assert [r["tag"] for r in until] == ["line2.pressure"]
    tag = query_samples(SampleFilter(tag="line1.temp"), db_path=db)
    assert len(tag) == 2
    ep = query_samples(SampleFilter(endpoint="plc1"), db_path=db)
    assert len(ep) == 4
    limited = query_samples(SampleFilter(limit=1), db_path=db)
    assert len(limited) == 1


@pytest.mark.unit
def test_latest_samples_dedupes_per_tag(db):
    latest = latest_samples(db_path=db)
    assert len(latest) == 3  # one per (endpoint, protocol, tag)
    temp = next(r for r in latest if r["tag"] == "line1.temp")
    assert temp["value"] == 22.0  # the newer write wins


@pytest.mark.unit
def test_count_and_missing_store_behaviour(tmp_path, db):
    assert count_samples(db) == 4
    missing = tmp_path / "nope.db"
    assert count_samples(missing) == 0
    assert latest_samples(db_path=missing) == []
    with pytest.raises(FileNotFoundError, match="No local store"):
        query_samples(SampleFilter(), db_path=missing)


@pytest.mark.unit
def test_filter_validation_fails_fast():
    with pytest.raises(ValueError, match="limit"):
        validate_filter(SampleFilter(limit=0))
    with pytest.raises(ValueError, match="limit"):
        validate_filter(SampleFilter(limit=10_000_001))
    with pytest.raises(ValueError, match="ISO-8601"):
        validate_filter(SampleFilter(since="yesterday"))
    with pytest.raises(ValueError, match="after"):
        validate_filter(SampleFilter(since="2026-07-02T00:00:00", until="2026-07-01T00:00:00"))


@pytest.mark.unit
def test_db_file_permissions_hardened(db):
    mode = stat.S_IMODE(db.stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700


@pytest.mark.unit
def test_sink_ignores_tsdb_connection_params(tmp_path):
    # The shared historian_push path passes host= by default — must not break.
    sink = SQLiteLocalSink(
        db_path=tmp_path / "d.db", host="localhost", port=6030, user="root", password="x"
    )
    written = sink.write(
        [{"metric": "t1", "value": 1.0, "numeric": True, "timestamp": "", "tags": {}}]
    )
    sink.close()
    assert written == 1
