"""Local SQLite sink + query layer — the queryable on-box store for collected OT data.

The "queryability layer" (docs/MARKET-INSIGHTS.md R5): operators need collected
data OUT — into Excel / Power BI / SQL / Grafana — in minutes, not a historian
project. This sink writes normalized samples to ``~/.iaiops/data.db`` (WAL,
0600, same hardening as the audit DB), and the query helpers here feed
``iaiops export``, the ``export_data`` MCP tool, and the Prometheus exporter.

Unlike the TSDB sinks (TDengine / IoTDB), this store also keeps non-numeric
values (as text) — SQLite's value column is dynamically typed. Timestamps are
stored as ISO-8601 text, so ``since``/``until`` filters compare lexically.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.governance.paths import ops_path

DB_FILENAME = "data.db"
SAMPLE_COLUMNS = ("ts", "endpoint", "protocol", "tag", "value", "quality", "unit")
DEFAULT_QUERY_LIMIT = 10_000
MAX_QUERY_LIMIT = 1_000_000

CREATE_SAMPLES_TABLE = """\
CREATE TABLE IF NOT EXISTS samples (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    endpoint TEXT NOT NULL DEFAULT '',
    protocol TEXT NOT NULL DEFAULT '',
    tag      TEXT NOT NULL,
    value,
    quality  TEXT NOT NULL DEFAULT '',
    unit     TEXT NOT NULL DEFAULT ''
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples (ts)",
    "CREATE INDEX IF NOT EXISTS idx_samples_tag_ts ON samples (tag, ts)",
    "CREATE INDEX IF NOT EXISTS idx_samples_endpoint_ts ON samples (endpoint, ts)",
)

_BUSY_TIMEOUT_MS = 5_000


def local_db_path() -> Path:
    """The local queryable store — ``<ops_home>/data.db`` (IAIOPS_HOME aware)."""
    return ops_path(DB_FILENAME)


def _normalize_ts(raw: Any) -> str:
    """Coerce a device timestamp to ISO-8601 text; empty → now (UTC).

    Unparseable device formats are kept verbatim (bounded/sanitized) — honesty
    over invention — but then sort/filter only among themselves.
    """
    text = s(raw, 40).strip()
    if not text:
        return datetime.now(UTC).isoformat()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def _harden_permissions(path: Path) -> None:
    """Best-effort 0700 dir / 0600 db+wal+shm, matching the audit DB hardening."""
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        try:
            if candidate.exists():
                os.chmod(candidate, 0o600)
        except OSError:
            pass


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn


class SQLiteLocalSink:
    """Uniform ``write(points) -> int`` sink over the local SQLite store.

    ``endpoint``/``protocol`` label the batch being written (the collectors know
    which endpoint they polled; normalized points don't carry it). The TSDB-style
    connection params (host/port/user/password) are accepted and ignored so the
    shared ``historian_push(sink="sqlite")`` path works unchanged; ``database``
    may override the db file path.
    """

    def __init__(self, db_path: Path | str | None = None, endpoint: str = "",
                 protocol: str = "", host: str = "", port: int = 0,
                 user: str = "", password: str = "",
                 database: str = "") -> None:
        del host, port, user, password  # local file store — no connection params
        chosen = db_path or database or local_db_path()
        self._path = Path(chosen).expanduser()
        self._endpoint = s(endpoint, 64)
        self._protocol = s(protocol, 32)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._conn = _connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(CREATE_SAMPLES_TABLE)
        for ddl in _INDEXES:
            self._conn.execute(ddl)
        self._conn.commit()
        _harden_permissions(self._path)

    def write(self, points: list[dict]) -> int:
        """Insert normalized points (numeric AND text values); returns the count."""
        if self._conn is None:
            self.connect()
        assert self._conn is not None  # for the type checker; connect() sets it
        rows = [self._row(p) for p in points]
        self._conn.executemany(
            "INSERT INTO samples (ts, endpoint, protocol, tag, value, quality, unit) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def _row(self, p: dict) -> tuple:
        tags = p.get("tags") or {}
        value: Any = float(p["value"]) if p.get("numeric") else s(p.get("value"), 256)
        return (
            _normalize_ts(p.get("timestamp")),
            self._endpoint,
            self._protocol,
            s(p.get("metric"), 128),
            value,
            s(tags.get("quality", ""), 48),
            s(tags.get("unit", ""), 32),
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass
            self._conn = None


# ─── query layer (feeds export / MCP tool / Prometheus exporter) ─────────────


@dataclass(frozen=True)
class SampleFilter:
    """Validated, immutable query filter over the local samples store."""

    since: str | None = None
    until: str | None = None
    endpoint: str | None = None
    tag: str | None = None
    limit: int = DEFAULT_QUERY_LIMIT


def _parse_bound(name: str, raw: str | None) -> str | None:
    """Validate an ISO-8601 time bound; returns the normalized text or None."""
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"Invalid --{name} {text!r}: expected ISO-8601, e.g. 2026-07-02T08:00:00."
        ) from exc


def validate_filter(flt: SampleFilter) -> SampleFilter:
    """Fail fast on bad bounds/limit; returns a normalized (new) filter."""
    limit = int(flt.limit)
    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise ValueError(f"limit must be 1..{MAX_QUERY_LIMIT} (got {flt.limit}).")
    since = _parse_bound("since", flt.since)
    until = _parse_bound("until", flt.until)
    if since and until and since > until:
        raise ValueError(f"--since {since} is after --until {until}.")
    return SampleFilter(
        since=since,
        until=until,
        endpoint=s(flt.endpoint, 64) if flt.endpoint else None,
        tag=s(flt.tag, 128) if flt.tag else None,
        limit=limit,
    )


def _where(flt: SampleFilter) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    for clause, value in (
        ("ts >= ?", flt.since),
        ("ts <= ?", flt.until),
        ("endpoint = ?", flt.endpoint),
        ("tag = ?", flt.tag),
    ):
        if value is not None:
            clauses.append(clause)
            params.append(value)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _require_store(db_path: Path | str | None) -> Path:
    path = Path(db_path).expanduser() if db_path else local_db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No local store at {path}. Collect first, e.g. "
            f"iaiops historian push --sink sqlite --input points.json."
        )
    return path


def query_samples(flt: SampleFilter, db_path: Path | str | None = None) -> list[dict]:
    """Filtered samples (oldest→newest), each as a SAMPLE_COLUMNS dict."""
    checked = validate_filter(flt)
    path = _require_store(db_path)
    where, params = _where(checked)
    # nosec-justification: ``where`` is built from a FIXED clause list; every
    # user-supplied value travels as a bound parameter, never interpolated.
    sql = (
        f"SELECT ts, endpoint, protocol, tag, value, quality, unit FROM samples"
        f"{where} ORDER BY ts, id LIMIT ?"  # nosec B608 — parameterized
    )
    conn = _connect(path)
    try:
        rows = conn.execute(sql, [*params, checked.limit]).fetchall()
    finally:
        conn.close()
    return [dict(zip(SAMPLE_COLUMNS, row)) for row in rows]


def latest_samples(db_path: Path | str | None = None, limit: int = 5_000) -> list[dict]:
    """Latest sample per (endpoint, protocol, tag). Missing store → [] (not an error)."""
    path = Path(db_path).expanduser() if db_path else local_db_path()
    if not path.exists():
        return []
    sql = (
        "SELECT t.ts, t.endpoint, t.protocol, t.tag, t.value, t.quality, t.unit "
        "FROM samples t JOIN (SELECT MAX(id) AS mid FROM samples "
        "GROUP BY endpoint, protocol, tag) m ON t.id = m.mid ORDER BY t.tag LIMIT ?"
    )
    conn = _connect(path)
    try:
        rows = conn.execute(sql, [max(1, min(int(limit), MAX_QUERY_LIMIT))]).fetchall()
    finally:
        conn.close()
    return [dict(zip(SAMPLE_COLUMNS, row)) for row in rows]


def count_samples(db_path: Path | str | None = None) -> int:
    """Total rows in the local store; missing store → 0."""
    path = Path(db_path).expanduser() if db_path else local_db_path()
    if not path.exists():
        return 0
    conn = _connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
    finally:
        conn.close()


__all__ = [
    "DB_FILENAME",
    "SAMPLE_COLUMNS",
    "DEFAULT_QUERY_LIMIT",
    "MAX_QUERY_LIMIT",
    "SQLiteLocalSink",
    "SampleFilter",
    "local_db_path",
    "validate_filter",
    "query_samples",
    "latest_samples",
    "count_samples",
]
