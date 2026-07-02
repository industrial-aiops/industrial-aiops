"""Historian READ integration (A7) — readers, RCA evidence, governed tools.

Covers: the sqlite reader round-trip over the real local store (via
``historian_push``), filter validation at the boundary, the TDengine / IoTDB
readers against mocked client libraries (query text + neutralized values
asserted), the RCA copilot with/without a configured historian (byte-identical
without; cited historian evidence with), and the two governed MCP tools
(marker + risk level + bounds + truncation flags).
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from iaiops.core.brain import rca_history
from iaiops.core.brain.rca import downtime_rca
from iaiops.core.runtime.config import AppConfig, HistorianConfig
from iaiops.core.sink.base import SinkError
from iaiops.core.sink.push import historian_push
from iaiops.core.sink.reader import (
    IoTDBReader,
    SQLiteReader,
    TDengineReader,
    get_reader,
)
from iaiops.core.sink.sqlite_local import SampleFilter
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.historian_tools import historian_coverage, historian_query

WINDOW = {"start": "2026-07-02T10:00:00+00:00", "asset": "line1"}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


def _seed(home, tag: str = "line1.temp", n: int = 12, value: float | None = None):
    """Write n points inside the 2h pre-incident window before WINDOW.start."""
    points = [
        {"ref": tag, "value": value if value is not None else float(i),
         "timestamp": f"2026-07-02T09:{10 + i:02d}:00+00:00"}
        for i in range(n)
    ]
    result = historian_push(points, "sqlite", db_path=home / "data.db")
    assert "error" not in result
    return home / "data.db"


# ─── sqlite reader (round-trip + validation) ─────────────────────────────────


@pytest.mark.unit
def test_sqlite_reader_roundtrip(home):
    db = _seed(home, n=10)
    reader = SQLiteReader(db_path=db)
    rows = reader.query(SampleFilter(tag="line1.temp",
                                     since="2026-07-02T09:12:00+00:00",
                                     until="2026-07-02T09:15:00+00:00"))
    assert [r["value"] for r in rows] == [2.0, 3.0, 4.0, 5.0]
    assert all(r["tag"] == "line1.temp" for r in rows)
    latest = reader.latest()
    assert latest and latest[0]["value"] == 9.0
    cov = reader.coverage()
    assert cov == [{"tag": "line1.temp", "rows": 10,
                    "first_ts": "2026-07-02T09:10:00+00:00",
                    "last_ts": "2026-07-02T09:19:00+00:00"}]


@pytest.mark.unit
def test_sqlite_reader_filter_validation(home):
    reader = SQLiteReader(db_path=_seed(home))
    with pytest.raises(ValueError, match="ISO-8601"):
        reader.query(SampleFilter(since="not-a-time"))
    with pytest.raises(ValueError, match="limit"):
        reader.query(SampleFilter(limit=0))
    with pytest.raises(ValueError, match="after"):
        reader.query(SampleFilter(since="2026-07-02T10:00:00",
                                  until="2026-07-02T09:00:00"))
    with pytest.raises(ValueError, match="limit"):
        reader.coverage(limit=0)


@pytest.mark.unit
def test_get_reader_registry_teaches_on_unknown():
    assert isinstance(get_reader("sqlite"), SQLiteReader)
    assert isinstance(get_reader("tdengine"), TDengineReader)
    assert isinstance(get_reader("iotdb"), IoTDBReader)
    with pytest.raises(SinkError, match="Supported: sqlite, tdengine, iotdb"):
        get_reader("influxdb")


# ─── TDengine reader (mocked taospy: query text + neutralized values) ────────


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self.rows = rows
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchall(self) -> list[tuple]:
        return self.rows


class _FakeTaosConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_taos(monkeypatch):
    cursor = _FakeCursor(rows=[("2026-07-02 09:30:00", 21.5, "line1.temp")])
    conn = _FakeTaosConn(cursor)
    mod = types.ModuleType("taos")
    mod.connect = lambda **kwargs: conn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "taos", mod)
    return cursor


@pytest.mark.unit
def test_tdengine_reader_query_sql_and_shape(fake_taos):
    reader = TDengineReader(database="iaiops; DROP", stable="ot_metric")
    rows = reader.query(SampleFilter(
        tag="line1.temp' OR '1'='1", since="2026-07-02T08:00:00+00:00",
        until="2026-07-02T10:00:00Z", limit=50,
    ))
    sql = fake_taos.executed[-1]
    # Identifiers sanitized, bounds normalized ISO, tag quote-escaped, limit int.
    assert sql == (
        "SELECT ts, `value`, metric FROM iaiops__DROP.ot_metric"
        " WHERE ts >= '2026-07-02T08:00:00+00:00'"
        " AND ts <= '2026-07-02T10:00:00+00:00'"
        " AND metric = 'line1.temp'' OR ''1''=''1'"
        " ORDER BY ts LIMIT 50"
    )
    assert rows == [{"ts": "2026-07-02 09:30:00", "endpoint": "", "protocol": "",
                     "tag": "line1.temp", "value": 21.5, "quality": "", "unit": ""}]


@pytest.mark.unit
def test_tdengine_reader_coverage_and_validation(fake_taos):
    fake_taos.rows = [("line1.temp", 42, "2026-07-01", "2026-07-02")]
    reader = TDengineReader()
    cov = reader.coverage(limit=10)
    assert fake_taos.executed[-1] == (
        "SELECT metric, COUNT(*), MIN(ts), MAX(ts) FROM iaiops.ot_metric "
        "GROUP BY metric LIMIT 10"
    )
    assert cov == [{"tag": "line1.temp", "rows": 42,
                    "first_ts": "2026-07-01", "last_ts": "2026-07-02"}]
    with pytest.raises(ValueError, match="ISO-8601"):
        reader.query(SampleFilter(since="yesterday"))
    with pytest.raises(ValueError, match="endpoint"):
        reader.query(SampleFilter(endpoint="line1"))


# ─── IoTDB reader (mocked session: query text + epoch-millis bounds) ─────────


class _FakeRecord:
    def __init__(self, ts_ms: int, fields: list[Any]):
        self._ts = ts_ms
        self._fields = fields

    def get_timestamp(self) -> int:
        return self._ts

    def get_fields(self) -> list[Any]:
        return self._fields


class _FakeDataSet:
    def __init__(self, columns: list[str], records: list[_FakeRecord]):
        self._columns = columns
        self._records = list(records)

    def get_column_names(self) -> list[str]:
        return self._columns

    def has_next(self) -> bool:
        return bool(self._records)

    def next(self) -> _FakeRecord:
        return self._records.pop(0)


class _FakeIoTDBSession:
    dataset: _FakeDataSet = _FakeDataSet([], [])
    executed: list[str] = []

    def __init__(self, *args: Any) -> None:
        pass

    def open(self, _enable_rpc_compression: bool) -> None:
        pass

    def execute_query_statement(self, sql: str) -> _FakeDataSet:
        _FakeIoTDBSession.executed.append(sql)
        return _FakeIoTDBSession.dataset

    def close(self) -> None:
        pass


@pytest.fixture()
def fake_iotdb(monkeypatch):
    _FakeIoTDBSession.executed = []
    pkg = types.ModuleType("iotdb")
    session_mod = types.ModuleType("iotdb.Session")
    session_mod.Session = _FakeIoTDBSession  # type: ignore[attr-defined]
    pkg.Session = session_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "iotdb", pkg)
    monkeypatch.setitem(sys.modules, "iotdb.Session", session_mod)
    return _FakeIoTDBSession


@pytest.mark.unit
def test_iotdb_reader_query_sql_and_shape(fake_iotdb):
    fake_iotdb.dataset = _FakeDataSet(
        ["Time", "root.iaiops.line1_temp.value"],
        [_FakeRecord(1_782_984_600_000, [21.5])],
    )
    reader = IoTDBReader()
    rows = reader.query(SampleFilter(
        tag="line1.temp", since="2026-07-02T08:00:00+00:00",
        until="2026-07-02T10:00:00+00:00", limit=50,
    ))
    # Path segment sanitized (dots → underscores), bounds are epoch-millis ints.
    assert fake_iotdb.executed[-1] == (
        "SELECT value FROM root.iaiops.line1_temp"
        " WHERE time >= 1782979200000 AND time <= 1782986400000"
        " ORDER BY time ASC LIMIT 50"
    )
    assert len(rows) == 1
    assert rows[0]["tag"] == "line1_temp"
    assert rows[0]["value"] == 21.5
    assert rows[0]["ts"].startswith("2026-07-02T")


@pytest.mark.unit
def test_iotdb_reader_coverage_parses_aggregates(fake_iotdb):
    fake_iotdb.dataset = _FakeDataSet(
        ["count(root.iaiops.t1.value)", "min_time(root.iaiops.t1.value)",
         "max_time(root.iaiops.t1.value)"],
        [_FakeRecord(0, [7, 1_782_979_200_000, 1_782_986_400_000])],
    )
    cov = IoTDBReader().coverage(limit=10)
    assert fake_iotdb.executed[-1] == (
        "SELECT COUNT(value), MIN_TIME(value), MAX_TIME(value) FROM root.iaiops.*"
    )
    assert len(cov) == 1
    assert cov[0]["tag"] == "t1"
    assert cov[0]["rows"] == 7
    assert cov[0]["first_ts"].startswith("2026-07-02T08:00:00")
    with pytest.raises(ValueError, match="endpoint"):
        IoTDBReader().query(SampleFilter(endpoint="line1"))


# ─── RCA: additive historian evidence ────────────────────────────────────────

_ALARMS = [{"source": "M1_DRIVE", "timestamp": "2026-07-02T09:59:30+00:00",
            "message": "motor overload trip"}]


@pytest.mark.unit
def test_gather_pre_incident_none_without_config():
    assert rca_history.gather_pre_incident(WINDOW, config=AppConfig()) is None
    assert rca_history.gather_pre_incident({}, config=AppConfig(
        historian=HistorianConfig(reader="sqlite"))) is None  # no window.start


@pytest.mark.unit
def test_rca_byte_identical_without_historian_config(home, monkeypatch):
    monkeypatch.setattr(rca_history, "load_config_env", lambda: AppConfig())
    from mcp_server.tools.diagnostics_tools import downtime_root_cause

    baseline = downtime_rca(WINDOW, alarms=_ALARMS)
    via_tool = downtime_root_cause(window=WINDOW, alarms=_ALARMS)
    assert via_tool == baseline
    assert downtime_rca(WINDOW, alarms=_ALARMS, historian=None) == baseline


@pytest.mark.unit
def test_rca_cites_historian_evidence_when_configured(home, monkeypatch):
    db = _seed(home, tag="line1.temp", n=12, value=7.0)  # flatline pre-incident
    cfg = AppConfig(historian=HistorianConfig(reader="sqlite", db_path=str(db)))
    monkeypatch.setattr(rca_history, "load_config_env", lambda: cfg)
    from mcp_server.tools.diagnostics_tools import downtime_root_cause

    result = downtime_root_cause(window=WINDOW, alarms=_ALARMS)
    summary = result["evidence_summary"]
    assert summary["historian_source"] == "historian:sqlite"
    assert summary["historian_tags_supplied"] == 1
    assert summary["historian_sample_count"] == 12
    cites = [e for h in result["hypotheses"] for e in h["evidence"]
             if e["signal"] == "historian_trend"]
    assert cites, "flatline pre-incident trend must be cited"
    assert cites[0]["source"] == "historian:sqlite"
    assert cites[0]["ref"] == "line1.temp"
    assert cites[0]["sample_count"] == 12
    assert cites[0]["window"] == {"since": "2026-07-02T08:00:00+00:00",
                                  "until": "2026-07-02T10:00:00+00:00"}
    # Additive: the alarm evidence from the baseline path is still present.
    assert summary["alarms_supplied"] == 1


@pytest.mark.unit
def test_gather_pre_incident_reader_failure_degrades_honestly(monkeypatch):
    cfg = AppConfig(historian=HistorianConfig(
        reader="sqlite", db_path="/nonexistent/nowhere.db"))
    bundle = rca_history.gather_pre_incident(WINDOW, config=cfg)
    assert bundle is not None
    assert bundle["tags"] == [] and bundle["sample_count"] == 0
    assert "No local store" in bundle["error"]
    # Even an error bundle keeps RCA working and honest.
    result = downtime_rca(WINDOW, alarms=_ALARMS, historian=bundle)
    assert result["evidence_summary"]["historian_error"]
    assert result["evidence_summary"]["historian_tags_supplied"] == 0


@pytest.mark.unit
def test_historian_config_validation():
    with pytest.raises(ValueError, match="unsupported"):
        HistorianConfig(reader="influxdb")
    opts = HistorianConfig(reader="sqlite", db_path="/tmp/x.db").reader_opts()
    assert opts == {"db_path": "/tmp/x.db"}


# ─── governed MCP tools: marker, bounds, truncation ──────────────────────────


def _no_site_config(monkeypatch):
    """Pin the tools to 'no historian: block' regardless of the dev machine."""
    import mcp_server.tools.historian_tools as ht

    monkeypatch.setattr(ht, "load_config_env", lambda: AppConfig())


@pytest.mark.unit
def test_historian_tools_governed_low_risk_and_registered():
    for tool in (historian_query, historian_coverage):
        assert getattr(tool, "_is_governed_tool", False) is True
        assert getattr(tool, "_risk_level", "") == "low"
    assert "historian_tools" in BRAIN_MODULES  # always-on brain module


@pytest.mark.unit
def test_historian_query_bounded_with_truncation_flag(home, monkeypatch):
    _no_site_config(monkeypatch)
    _seed(home, n=12)
    full = historian_query(tag="line1.temp")
    assert "error" not in full
    assert full["reader"] == "sqlite" and full["source"] == "historian:sqlite"
    assert full["rows"] == 12 and full["truncated"] is False
    capped = historian_query(tag="line1.temp", limit=5)
    assert capped["rows"] == 5 and capped["truncated"] is True
    assert len(capped["samples"]) == 5


@pytest.mark.unit
def test_historian_query_validation_teaches(home, monkeypatch):
    _no_site_config(monkeypatch)
    _seed(home, n=1)
    assert "tag is required" in historian_query(tag=" ")["error"]
    assert "limit" in historian_query(tag="t", limit=0)["error"]
    assert "limit" in historian_query(tag="t", limit=999_999)["error"]
    assert "ISO-8601" in historian_query(tag="t", since="soon")["error"]
    assert "Unknown historian reader" in historian_query(tag="t", reader="pi")["error"]


@pytest.mark.unit
def test_historian_coverage_bounded(home, monkeypatch):
    _no_site_config(monkeypatch)
    for i in range(3):
        _seed(home, tag=f"tag{i}", n=2)
    cov = historian_coverage()
    assert cov["tag_count"] == 3 and cov["truncated"] is False
    assert {t["tag"] for t in cov["tags"]} == {"tag0", "tag1", "tag2"}
    assert all(t["rows"] == 2 for t in cov["tags"])
    capped = historian_coverage(limit=2)
    assert capped["tag_count"] == 2 and capped["truncated"] is True
    assert "limit" in historian_coverage(limit=0)["error"]


@pytest.mark.unit
def test_historian_tools_missing_store_teaches(home, monkeypatch):
    _no_site_config(monkeypatch)
    assert "No local store" in historian_query(tag="t")["error"]
    assert "No local store" in historian_coverage()["error"]
