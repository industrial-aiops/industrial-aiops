"""Open-format export (queryability layer) — CSV / SQLite golden path + validation.

Parquet is exercised both ways: the teaching error when pyarrow is absent, and a
real write→read roundtrip when it happens to be installed.
"""

from __future__ import annotations

import csv
import importlib.util
import sqlite3

import pytest

from iaiops.core.sink.export import EXPORT_FORMATS, export_samples
from iaiops.core.sink.push import historian_push
from iaiops.core.sink.sqlite_local import SAMPLE_COLUMNS

POINTS = [
    {
        "ref": "line1.temp",
        "value": 21.5,
        "timestamp": "2026-07-01T00:00:00Z",
        "quality": "good",
        "unit": "C",
    },
    {"ref": "line1.state", "value": "RUNNING", "timestamp": "2026-07-01T00:30:00Z"},
    {"ref": "line2.pressure", "value": 3.1, "timestamp": "2026-07-01T01:00:00Z"},
]

_HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "data.db"
    assert "error" not in historian_push(
        POINTS, "sqlite", db_path=path, endpoint="plc1", protocol="modbus"
    )
    return path


@pytest.mark.unit
def test_csv_export_golden_path(store, tmp_path):
    out = tmp_path / "out.csv"
    result = export_samples("csv", out, db_path=store)
    assert result == {"format": "csv", "path": str(out), "rows": 3}
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert set(rows[0]) == set(SAMPLE_COLUMNS)
    assert rows[0]["tag"] == "line1.temp" and rows[0]["value"] == "21.5"
    assert rows[1]["value"] == "RUNNING"


@pytest.mark.unit
def test_csv_export_applies_filters(store, tmp_path):
    out = tmp_path / "temp-only.csv"
    result = export_samples("csv", out, tag="line1.temp", db_path=store)
    assert result["rows"] == 1
    result = export_samples("csv", out, since="2026-07-01T00:30:00Z", limit=1, db_path=store)
    assert result["rows"] == 1


@pytest.mark.unit
def test_sqlite_export_golden_path(store, tmp_path):
    out = tmp_path / "out.db"
    result = export_samples("sqlite", out, db_path=store)
    assert result["rows"] == 3
    conn = sqlite3.connect(str(out))
    try:
        assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 3
        value = conn.execute("SELECT value FROM samples WHERE tag = 'line1.temp'").fetchone()[0]
        assert value == 21.5
    finally:
        conn.close()
    # Re-export overwrites (fresh snapshot), not appends.
    assert export_samples("sqlite", out, db_path=store)["rows"] == 3
    conn = sqlite3.connect(str(out))
    try:
        assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 3
    finally:
        conn.close()


@pytest.mark.unit
@pytest.mark.skipif(_HAS_PYARROW, reason="pyarrow installed — teaching error N/A")
def test_parquet_without_pyarrow_teaches_the_extra(store, tmp_path):
    with pytest.raises(ValueError, match=r"iaiops\[export\]"):
        export_samples("parquet", tmp_path / "out.parquet", db_path=store)


@pytest.mark.unit
@pytest.mark.skipif(not _HAS_PYARROW, reason="pyarrow not installed")
def test_parquet_roundtrip_when_pyarrow_present(store, tmp_path):
    import pyarrow.parquet as pq

    out = tmp_path / "out.parquet"
    assert export_samples("parquet", out, db_path=store)["rows"] == 3
    table = pq.read_table(str(out))
    assert table.num_rows == 3
    assert set(table.column_names) == set(SAMPLE_COLUMNS)


@pytest.mark.unit
def test_export_input_validation_fails_fast(store, tmp_path):
    with pytest.raises(ValueError, match="Unknown export format"):
        export_samples("xlsx", tmp_path / "o.xlsx", db_path=store)
    with pytest.raises(ValueError, match="directory"):
        export_samples("csv", tmp_path, db_path=store)
    with pytest.raises(ValueError, match="ISO-8601"):
        export_samples("csv", tmp_path / "o.csv", since="not-a-time", db_path=store)
    with pytest.raises(ValueError, match="limit"):
        export_samples("csv", tmp_path / "o.csv", limit=0, db_path=store)
    with pytest.raises(FileNotFoundError, match="No local store"):
        export_samples("csv", tmp_path / "o.csv", db_path=tmp_path / "missing.db")
    assert set(EXPORT_FORMATS) == {"csv", "sqlite", "parquet"}
