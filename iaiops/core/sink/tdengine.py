"""TDengine historian sink — write OT telemetry to TDengine.

TDengine is a domestic (国产) time-series database popular for industrial/IoT
historians. ``taospy`` (the official Python connector) is an OPTIONAL extra
(``pip install iaiops[tdengine]``) imported LAZILY. The connect/insert surface +
SQL dialect were verified against a live taosd 3.3 (write→read round-trip,
2026-06-30) — which is how the ``value`` reserved-word DDL bug was caught. The
path is isolated behind the uniform ``write(points) -> int`` interface (also
mock-testable). NB: ``value`` must be back-quoted in DDL (TDengine reserved word).
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.sink.base import SinkError


class TDengineSink:
    """Uniform sink over a TDengine connection (待核实)."""

    def __init__(self, host: str = "localhost", port: int = 6030,
                 user: str = "root", password: str = "taosdata",
                 database: str = "iaiops", stable: str = "ot_metric") -> None:
        self._host = host
        self._port = int(port or 6030)
        self._user = user
        self._password = password
        # Sanitize SQL identifiers once at construction (alnum/underscore only) so
        # every interpolation site is injection-safe.
        self._database = _safe_ident(database, "iaiops")
        self._stable = _safe_ident(stable, "ot_metric")
        self._conn = None

    def connect(self) -> None:
        try:
            import taos
        except ImportError as exc:  # pragma: no cover — only without taospy
            raise SinkError(
                "The 'taospy' package is not installed. Install the TDengine sink: "
                "'pip install iaiops[tdengine]'."
            ) from exc
        self._conn = taos.connect(
            host=self._host, port=self._port, user=self._user,
            password=self._password,
        )
        cur = self._conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {self._database}")  # nosec B608 — ident sanitized
        cur.execute(f"USE {self._database}")  # nosec B608 — ident sanitized
        # Super-table: ts + value + a metric tag (one sub-table per metric).
        # ``value`` is a TDengine RESERVED WORD — it must be back-quoted in DDL or
        # the CREATE STABLE fails with a syntax error (verified against a live
        # taosd 3.3, 2026-06-30). The INSERTs are positional (no column list) so
        # they need no quoting.
        cur.execute(  # nosec B608 — ident sanitized
            f"CREATE STABLE IF NOT EXISTS {self._stable} "
            f"(ts TIMESTAMP, `value` DOUBLE) TAGS (metric BINARY(160))"
        )

    def write(self, points: list[dict]) -> int:
        """Insert normalized numeric points; returns the count written."""
        if self._conn is None:
            self.connect()
        cur = self._conn.cursor()
        written = 0
        for p in points:
            if not p.get("numeric"):
                continue  # TDengine value column is DOUBLE — skip non-numeric
            sub = _sanitize_table(p["metric"])  # alnum/underscore only
            ts = _ts_clause(p.get("timestamp"))  # quote-escaped literal / NOW
            # Injection-safe: sub + self._stable are alnum/underscore only, the tag
            # AND the timestamp are single-quote-escaped (_esc), and the value is a
            # Python float. taospy's INSERT…USING…TAGS (auto sub-table) can't be
            # parameterized, so the string is built but every field is neutralized.
            sql = (
                f"INSERT INTO {sub} USING {self._stable} TAGS ('{_esc(p['metric'])}') "  # nosec B608
                f"VALUES ({ts}, {float(p['value'])})"
            )
            cur.execute(sql)
            written += 1
        return written

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


def _sanitize_table(metric: str) -> str:
    """Make a safe TDengine sub-table name from a metric (alnum/underscore)."""
    safe = "".join(c if c.isalnum() else "_" for c in str(metric))[:180]
    return f"m_{safe}" if safe else "m_unknown"


def _ts_clause(timestamp: Any) -> str:
    """A TDengine timestamp literal (single-quote-escaped), or NOW when absent."""
    text = s(str(timestamp or "").strip(), 40)
    return f"'{_esc(text)}'" if text else "NOW"


def _esc(value: str) -> str:
    """Escape single quotes in a string literal."""
    return str(value).replace("'", "''")[:160]


def _safe_ident(value: str, fallback: str) -> str:
    """Sanitize a SQL identifier (db / super-table) to alnum/underscore only."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(value))[:180]
    return safe or fallback


__all__ = ["TDengineSink"]
