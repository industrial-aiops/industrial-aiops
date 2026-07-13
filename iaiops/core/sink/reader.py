"""Historian READERS — query historical windows back OUT of the sinks (A7).

The sinks (:mod:`iaiops.core.sink`) made TDengine / IoTDB / local SQLite
write targets; this module is the matching READ side so the RCA copilot (and
the ``historian_query`` / ``historian_coverage`` tools) can pull a
pre-incident window instead of relying on short live samples. One reader per
sink, over the SAME table/timeseries layout the sink writes:

  * ``sqlite``   — delegates to the existing query layer (``query_samples`` /
    ``SampleFilter`` / ``latest_samples``) over ``~/.iaiops/data.db``.
  * ``tdengine`` — SELECT over the super-table the sink creates (``ts`` +
    back-quoted ``value`` + a ``metric`` tag, one sub-table per metric).
  * ``iotdb``    — SELECT over the ``<database>.<metric>.value`` timeseries the
    sink's ``insert_record`` writes.

TSDB client libraries are the SAME optional extras as the sinks
(``iaiops[tdengine]`` / ``iaiops[iotdb]``), imported lazily with a teaching
error when missing. Filters are validated at the boundary (ISO-8601 bounds,
capped limits) via the shared ``validate_filter``; SQLite queries are fully
parameterized, and the TSDB dialects (whose clients take no bind parameters)
interpolate ONLY validated/escaped values — sanitized identifiers, normalized
ISO timestamps, quote-escaped tag literals, and Python ints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from iaiops.core.brain._shared import num, s
from iaiops.core.sink.base import SinkError
from iaiops.core.sink.sqlite_local import (
    MAX_QUERY_LIMIT,
    SAMPLE_COLUMNS,
    SampleFilter,
    _connect,
    _require_store,
    latest_samples,
    local_db_path,
    query_samples,
    validate_filter,
)
from iaiops.core.sink.tdengine import _esc, _safe_ident

SUPPORTED_READERS = ("sqlite", "tdengine", "iotdb")
DEFAULT_COVERAGE_LIMIT = 500
MAX_COVERAGE_LIMIT = 10_000


class HistorianReader(Protocol):
    """Uniform read surface over a historian (mirrors the sink protocol)."""

    def query(self, flt: SampleFilter) -> list[dict]:
        """Filtered samples (oldest→newest) as SAMPLE_COLUMNS dicts."""
        ...

    def latest(self, limit: int = 5_000) -> list[dict]:
        """Latest sample per tag, bounded by ``limit``."""
        ...

    def coverage(self, limit: int = DEFAULT_COVERAGE_LIMIT) -> list[dict]:
        """Per-tag ``{tag, rows, first_ts, last_ts}`` rows, bounded."""
        ...

    def close(self) -> None:
        """Release any client connection (best-effort)."""
        ...


def _cap_coverage_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit must be an integer (got {limit!r}).") from exc
    if not 1 <= value <= MAX_COVERAGE_LIMIT:
        raise ValueError(f"limit must be 1..{MAX_COVERAGE_LIMIT} (got {limit}).")
    return value


def _sample_row(ts: str, tag: str, value: Any) -> dict:
    """A SAMPLE_COLUMNS-shaped dict for TSDB rows (no endpoint/quality/unit)."""
    return dict(zip(SAMPLE_COLUMNS, (s(ts, 40), "", "", s(tag, 128), value, "", "")))


def _reject_endpoint_filter(flt: SampleFilter, reader: str) -> None:
    """The TSDB sinks store no endpoint label — teach instead of silently ignoring."""
    if flt.endpoint:
        raise ValueError(
            f"The {reader} historian stores no endpoint label (only tag/metric); "
            f"drop the endpoint filter or use the sqlite reader."
        )


# ─── sqlite (delegates to the existing query layer) ──────────────────────────


class SQLiteReader:
    """Reader over the local SQLite store — thin delegate to sqlite_local."""

    def __init__(
        self, db_path: Path | str | None = None, database: str = "", **_ignored: Any
    ) -> None:
        self._path = (
            Path(db_path or database).expanduser() if (db_path or database) else local_db_path()
        )

    def query(self, flt: SampleFilter) -> list[dict]:
        return query_samples(flt, db_path=self._path)

    def latest(self, limit: int = 5_000) -> list[dict]:
        return latest_samples(db_path=self._path, limit=limit)

    def coverage(self, limit: int = DEFAULT_COVERAGE_LIMIT) -> list[dict]:
        capped = _cap_coverage_limit(limit)
        path = _require_store(self._path)
        conn = _connect(path)
        try:
            rows = conn.execute(
                "SELECT tag, COUNT(*), MIN(ts), MAX(ts) FROM samples "
                "GROUP BY tag ORDER BY tag LIMIT ?",
                [capped],
            ).fetchall()
        finally:
            conn.close()
        return [{"tag": r[0], "rows": int(r[1]), "first_ts": r[2], "last_ts": r[3]} for r in rows]

    def close(self) -> None:
        """Connections are per-call in the query layer — nothing to release."""


# ─── TDengine (matches TDengineSink's super-table layout) ────────────────────


class TDengineReader:
    """Reader over the super-table ``TDengineSink`` writes (待核实).

    taospy's cursor takes no bind parameters, so every interpolated value is
    neutralized first: identifiers are alnum/underscore-sanitized, time bounds
    are ``validate_filter``-normalized ISO text, tag literals are
    single-quote-escaped, and the limit is a validated Python int.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6030,
        user: str = "root",
        password: str = "taosdata",
        database: str = "iaiops",
        stable: str = "ot_metric",
        **_ignored: Any,
    ) -> None:
        self._host = host
        self._port = int(port or 6030)
        self._user = user
        self._password = password
        self._database = _safe_ident(database, "iaiops")
        self._stable = _safe_ident(stable, "ot_metric")
        self._conn: Any = None

    def connect(self) -> None:
        try:
            import taos
        except ImportError as exc:  # pragma: no cover — only without taospy
            raise SinkError(
                "The 'taospy' package is not installed. Install the TDengine "
                "reader (same extra as the sink): 'pip install iaiops[tdengine]'."
            ) from exc
        self._conn = taos.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
        )

    def _cursor(self) -> Any:
        if self._conn is None:
            self.connect()
        return self._conn.cursor()

    def query(self, flt: SampleFilter) -> list[dict]:
        checked = validate_filter(flt)
        _reject_endpoint_filter(checked, "tdengine")
        clauses: list[str] = []
        if checked.since:
            clauses.append(f"ts >= '{_esc(checked.since)}'")
        if checked.until:
            clauses.append(f"ts <= '{_esc(checked.until)}'")
        if checked.tag:
            clauses.append(f"metric = '{_esc(checked.tag)}'")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # Injection-safe: idents sanitized at construction; bounds are validated
        # ISO text; the tag is quote-escaped; the limit is a validated int.
        sql = (
            f"SELECT ts, `value`, metric FROM {self._database}.{self._stable}"
            f"{where} ORDER BY ts LIMIT {int(checked.limit)}"  # nosec B608
        )
        cur = self._cursor()
        cur.execute(sql)
        return [_sample_row(str(r[0]), str(r[2]), num(r[1])) for r in cur.fetchall()]

    def latest(self, limit: int = 5_000) -> list[dict]:
        capped = max(1, min(int(limit), MAX_QUERY_LIMIT))
        # Injection-safe: idents sanitized at construction, limit is a validated int.
        sql = (
            f"SELECT LAST(ts), LAST(`value`), metric "  # nosec B608
            f"FROM {self._database}.{self._stable} GROUP BY metric LIMIT {capped}"
        )
        cur = self._cursor()
        cur.execute(sql)
        return [_sample_row(str(r[0]), str(r[2]), num(r[1])) for r in cur.fetchall()]

    def coverage(self, limit: int = DEFAULT_COVERAGE_LIMIT) -> list[dict]:
        capped = _cap_coverage_limit(limit)
        # Injection-safe: idents sanitized at construction, limit is a validated int.
        sql = (
            f"SELECT metric, COUNT(*), MIN(ts), MAX(ts) "  # nosec B608
            f"FROM {self._database}.{self._stable} GROUP BY metric LIMIT {capped}"
        )
        cur = self._cursor()
        cur.execute(sql)
        return [
            {
                "tag": s(str(r[0]), 128),
                "rows": int(r[1]),
                "first_ts": s(str(r[2]), 40),
                "last_ts": s(str(r[3]), 40),
            }
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


# ─── IoTDB (matches IoTDBSink's <database>.<metric>.value timeseries) ────────


class IoTDBReader:
    """Reader over the timeseries ``IoTDBSink`` writes (待核实).

    IoTDB's ``execute_query_statement`` takes no bind parameters, so the path
    segment is sanitized exactly like the sink's write path and the time bounds
    are validated ISO timestamps converted to epoch-millis Python ints.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6667,
        user: str = "root",
        password: str = "root",
        database: str = "root.iaiops",
        **_ignored: Any,
    ) -> None:
        self._host = host
        self._port = int(port or 6667)
        self._user = user
        self._password = password
        self._database = database.rstrip(".")
        self._session: Any = None

    def connect(self) -> None:
        try:
            from iotdb.Session import Session
        except ImportError as exc:  # pragma: no cover — only without apache-iotdb
            raise SinkError(
                "The 'apache-iotdb' package is not installed. Install the IoTDB "
                "reader (same extra as the sink): 'pip install iaiops[iotdb]'."
            ) from exc
        self._session = Session(self._host, self._port, self._user, self._password)
        self._session.open(False)

    def _execute(self, sql: str) -> Any:
        if self._session is None:
            self.connect()
        return self._session.execute_query_statement(sql)

    def _device(self, tag: str | None) -> str:
        from iaiops.core.sink.iotdb import _sanitize_path

        return f"{self._database}.{_sanitize_path(tag)}" if tag else f"{self._database}.*"

    def query(self, flt: SampleFilter) -> list[dict]:
        checked = validate_filter(flt)
        _reject_endpoint_filter(checked, "iotdb")
        clauses: list[str] = []
        if checked.since:
            clauses.append(f"time >= {_iso_to_millis(checked.since)}")
        if checked.until:
            clauses.append(f"time <= {_iso_to_millis(checked.until)}")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # Injection-safe: the device path is sanitized (alnum/underscore segment),
        # bounds are epoch-millis ints, and the limit is a validated int.
        sql = (
            f"SELECT value FROM {self._device(checked.tag)}"
            f"{where} ORDER BY time ASC LIMIT {int(checked.limit)}"  # nosec B608
        )
        return self._collect_rows(self._execute(sql))

    def latest(self, limit: int = 5_000) -> list[dict]:
        capped = max(1, min(int(limit), MAX_QUERY_LIMIT))
        # IoTDB "last" query: one latest row per timeseries.
        sql = f"SELECT LAST value FROM {self._database}.* LIMIT {capped}"  # nosec B608
        return self._collect_rows(self._execute(sql), last_query=True)

    def coverage(self, limit: int = DEFAULT_COVERAGE_LIMIT) -> list[dict]:
        capped = _cap_coverage_limit(limit)
        # Injection-safe: the path prefix comes from validated config, no user input.
        sql = (
            f"SELECT COUNT(value), MIN_TIME(value), MAX_TIME(value) "  # nosec B608
            f"FROM {self._database}.*"
        )
        dataset = self._execute(sql)
        columns = [str(c) for c in dataset.get_column_names()]
        out: list[dict] = []
        per_tag: dict[str, dict] = {}
        for record in _iter_records(dataset):
            for col, field in zip(columns, record.get_fields()):
                func, tag = _parse_aggregate_column(col, self._database)
                if not func:
                    continue
                entry = per_tag.setdefault(tag, {"tag": tag})
                value = _field_value(field)
                if func == "count":
                    entry["rows"] = int(value or 0)
                elif func == "min_time":
                    entry["first_ts"] = _millis_to_iso(value)
                elif func == "max_time":
                    entry["last_ts"] = _millis_to_iso(value)
        for tag in sorted(per_tag)[:capped]:
            entry = per_tag[tag]
            out.append(
                {
                    "tag": entry["tag"],
                    "rows": entry.get("rows", 0),
                    "first_ts": entry.get("first_ts", ""),
                    "last_ts": entry.get("last_ts", ""),
                }
            )
        return out

    def _collect_rows(self, dataset: Any, last_query: bool = False) -> list[dict]:
        columns = [str(c) for c in dataset.get_column_names()]
        rows: list[dict] = []
        for record in _iter_records(dataset):
            ts = _millis_to_iso(record.get_timestamp())
            fields = record.get_fields()
            if last_query:
                # LAST query shape: Time | timeseries | value | dataType.
                tag = _tag_from_path(str(_field_value(fields[0])), self._database)
                rows.append(_sample_row(ts, tag, num(_field_value(fields[1]))))
                continue
            for col, field in zip(_value_columns(columns), fields):
                value = _field_value(field)
                if value is None:
                    continue
                rows.append(_sample_row(ts, _tag_from_path(col, self._database), num(value)))
        return rows

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


def _iter_records(dataset: Any):
    while dataset.has_next():
        yield dataset.next()


def _value_columns(columns: list[str]) -> list[str]:
    """Data columns of a SELECT result (everything after the Time column)."""
    return [c for c in columns if c.lower() != "time"]


def _field_value(field: Any) -> Any:
    """Extract a python value from an IoTDB Field (or pass a scalar through)."""
    getter = getattr(field, "get_object_value", None)
    if callable(getter):
        try:
            return getter(field.get_data_type())
        except Exception:  # noqa: BLE001 — fall through to str below
            pass
    if hasattr(field, "get_string_value"):
        try:
            return field.get_string_value()
        except Exception:  # noqa: BLE001 — unknown field shape → verbatim
            pass
    return field


def _tag_from_path(column: str, database: str) -> str:
    """``root.iaiops.<tag>.value`` → ``<tag>`` (tolerates other shapes)."""
    text = str(column)
    prefix = f"{database}."
    if text.startswith(prefix):
        text = text[len(prefix) :]
    if text.endswith(".value"):
        text = text[: -len(".value")]
    return s(text, 128)


def _parse_aggregate_column(column: str, database: str) -> tuple[str, str]:
    """``COUNT(root.iaiops.t1.value)`` → ``("count", "t1")``; else ("", "")."""
    text = str(column).strip()
    if "(" not in text or not text.endswith(")"):
        return "", ""
    func, inner = text[:-1].split("(", 1)
    func = func.strip().lower()
    if func not in ("count", "min_time", "max_time"):
        return "", ""
    return func, _tag_from_path(inner.strip(), database)


def _iso_to_millis(iso_text: str) -> int:
    """Validated ISO-8601 text → epoch-millis (naive treated as UTC)."""
    from datetime import UTC, datetime

    dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _millis_to_iso(millis: Any) -> str:
    from datetime import UTC, datetime

    value = num(millis)
    if value is None:
        return ""
    return datetime.fromtimestamp(value / 1000.0, tz=UTC).isoformat()


# ─── factory (mirrors get_sink) ──────────────────────────────────────────────


def get_reader(kind: str, **opts: Any) -> HistorianReader:
    """Return a historian reader for ``kind`` (sqlite / tdengine / iotdb)."""
    k = (kind or "").strip().lower()
    if k == "sqlite":
        return SQLiteReader(**opts)
    if k == "tdengine":
        return TDengineReader(**opts)
    if k == "iotdb":
        return IoTDBReader(**opts)
    raise SinkError(
        f"Unknown historian reader '{kind}'. Supported: {', '.join(SUPPORTED_READERS)}."
    )


__all__ = [
    "HistorianReader",
    "SQLiteReader",
    "TDengineReader",
    "IoTDBReader",
    "get_reader",
    "SUPPORTED_READERS",
    "DEFAULT_COVERAGE_LIMIT",
    "MAX_COVERAGE_LIMIT",
]
