"""Apache IoTDB historian sink — write OT telemetry to IoTDB.

Apache IoTDB is an open, increasingly domestic-adopted time-series database for
industrial/IoT historians. ``apache-iotdb`` is an OPTIONAL extra
(``pip install iaiops[iotdb]``) imported LAZILY. The Session insert surface was
verified against a live IoTDB server (write→read round-trip via this sink,
2026-06-30) — isolated behind the uniform ``write(points) -> int`` interface
(also mock-testable).
"""

from __future__ import annotations

from iaiops.core.sink.base import SinkError


class IoTDBSink:
    """Uniform sink over an IoTDB Session (待核实)."""

    def __init__(self, host: str = "localhost", port: int = 6667,
                 user: str = "root", password: str = "root",
                 database: str = "root.iaiops") -> None:
        self._host = host
        self._port = int(port or 6667)
        self._user = user
        self._password = password
        self._database = database.rstrip(".")
        self._session = None

    def connect(self) -> None:
        try:
            from iotdb.Session import Session
        except ImportError as exc:  # pragma: no cover — only without apache-iotdb
            raise SinkError(
                "The 'apache-iotdb' package is not installed. Install the IoTDB sink: "
                "'pip install iaiops[iotdb]'."
            ) from exc
        self._session = Session(self._host, self._port, self._user, self._password)
        self._session.open(False)

    def write(self, points: list[dict]) -> int:
        """Insert normalized numeric points as IoTDB records; returns count written."""
        if self._session is None:
            self.connect()
        written = 0
        for p in points:
            if not p.get("numeric"):
                continue
            device = f"{self._database}.{_sanitize_path(p['metric'])}"
            ts = _ts_millis(p.get("timestamp"))
            # insert_record(device_id, time, measurements, data_types, values)
            self._session.insert_record(
                device, ts, ["value"], [_double_type()], [float(p["value"])]
            )
            written += 1
        return written

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


def _double_type():
    """Return IoTDB's DOUBLE TSDataType (lazy; only reached when the lib is present)."""
    from iotdb.utils.IoTDBConstants import TSDataType

    return TSDataType.DOUBLE


def _sanitize_path(metric: str) -> str:
    """IoTDB path segment from a metric (no dots/special chars in a node name)."""
    safe = "".join(c if c.isalnum() else "_" for c in str(metric))[:180]
    return safe or "unknown"


def _ts_millis(timestamp) -> int:
    """Parse an ISO timestamp to epoch-millis (UTC).

    A naive timestamp is treated as UTC (not the host's local tz) so writes are
    deterministic across machines. A missing/unparseable timestamp falls back to
    'now' (UTC) — never epoch 0, which would silently store the point at 1970.
    """
    from datetime import UTC, datetime

    text = str(timestamp or "").strip()
    if text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return int(datetime.now(tz=UTC).timestamp() * 1000)


__all__ = ["IoTDBSink"]
