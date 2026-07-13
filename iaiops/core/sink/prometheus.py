"""Prometheus/Grafana bridge — expose the local SQLite sink as /metrics.

Renders Prometheus text format 0.0.4 from the local store (``~/.iaiops/data.db``):
the latest numeric value per tag as ``iaiops_tag_value{endpoint,protocol,tag,unit}``
gauges, plus internal counters (samples written, audit events, tool errors from
the audit log). Served by a stdlib ``http.server`` thread — no new hard
dependency — bound to 127.0.0.1 unless the operator explicitly widens it.
See docs/GRAFANA.md for the scrape config + dashboard recipe.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from iaiops.core.brain._shared import num
from iaiops.core.governance.paths import ops_path
from iaiops.core.sink.sqlite_local import count_samples, latest_samples

_log = logging.getLogger("iaiops.prometheus")

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9184
GAUGE_NAME = "iaiops_tag_value"
MAX_SERIES = 5_000


def _escape_label(value: object) -> str:
    """Escape a label value per the Prometheus text exposition format."""
    return (
        str(value if value is not None else "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _gauge_lines(db_path: Path | str | None) -> list[str]:
    lines = [
        f"# HELP {GAUGE_NAME} Latest collected value per OT tag (from the local SQLite sink).",
        f"# TYPE {GAUGE_NAME} gauge",
    ]
    for sample in latest_samples(db_path, limit=MAX_SERIES):
        value = num(sample.get("value"))
        if value is None:
            continue  # gauges are numeric; text values stay export-only
        labels = ",".join(
            f'{name}="{_escape_label(sample.get(name, ""))}"'
            for name in ("endpoint", "protocol", "tag", "unit")
        )
        lines.append(f"{GAUGE_NAME}{{{labels}}} {value}")
    return lines


def _audit_counts(audit_db_path: Path | str | None) -> tuple[int, int]:
    """(total audit events, tool errors) from audit.db; missing/broken → (0, 0)."""
    path = Path(audit_db_path).expanduser() if audit_db_path else ops_path("audit.db")
    if not path.exists():
        return 0, 0
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            total = int(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
            errors = int(
                conn.execute("SELECT COUNT(*) FROM audit_log WHERE status != 'ok'").fetchone()[0]
            )
        finally:
            conn.close()
        return total, errors
    except sqlite3.Error:
        _log.warning("Could not read audit counters from %s", path, exc_info=True)
        return 0, 0


def render_metrics(
    db_path: Path | str | None = None,
    audit_db_path: Path | str | None = None,
) -> str:
    """Render the full Prometheus text-format payload (gauges + counters)."""
    audit_total, tool_errors = _audit_counts(audit_db_path)
    counters = (
        (
            "iaiops_samples_written_total",
            "Rows in the local SQLite sink (data.db).",
            count_samples(db_path),
        ),
        (
            "iaiops_audit_events_total",
            "Governed tool calls recorded in the audit log.",
            audit_total,
        ),
        (
            "iaiops_tool_errors_total",
            "Governed tool calls whose audit status is not 'ok'.",
            tool_errors,
        ),
    )
    lines = _gauge_lines(db_path)
    for name, help_text, value in counters:
        lines.extend(
            (
                f"# HELP {name} {help_text}",
                f"# TYPE {name} counter",
                f"{name} {int(value)}",
            )
        )
    return "\n".join(lines) + "\n"


class _MetricsHandler(BaseHTTPRequestHandler):
    """GET /metrics → text format 0.0.4; anything else → 404."""

    server: MetricsHTTPServer  # narrowed for db-path access

    def do_GET(self) -> None:  # noqa: N802 — http.server API name
        if self.path.split("?", 1)[0] not in ("/metrics", "/"):
            self.send_error(404, "Not found - scrape /metrics")
            return
        try:
            body = render_metrics(self.server.db_path, self.server.audit_db_path)
        except Exception:  # noqa: BLE001 — never leak internals to a scraper
            _log.error("metrics render failed", exc_info=True)
            self.send_error(500, "metrics unavailable")
            return
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        _log.debug("metrics http: " + format, *args)


class MetricsHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the store paths for the handler."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        db_path: Path | str | None = None,
        audit_db_path: Path | str | None = None,
    ) -> None:
        super().__init__(address, _MetricsHandler)
        self.db_path = db_path
        self.audit_db_path = audit_db_path


class MetricsServer:
    """Prometheus exporter over the local store, on a background thread.

    Binds 127.0.0.1 by default; pass an explicit host to widen (0.0.0.0 logs a
    loud warning — tag names/endpoint labels become visible to the network).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        db_path: Path | str | None = None,
        audit_db_path: Path | str | None = None,
    ) -> None:
        if not 0 <= int(port) <= 65535:
            raise ValueError(f"port must be 0..65535 (got {port}).")
        if host == "0.0.0.0":  # nosec B104 — operator's explicit choice; warned
            _log.warning(
                "Metrics endpoint bound to 0.0.0.0 — tag/endpoint names are "
                "exposed to every host that can reach this machine. Prefer "
                "127.0.0.1 + a local Prometheus, or firewall the port."
            )
        self._httpd = MetricsHTTPServer((host, int(port)), db_path, audit_db_path)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port (useful when constructed with port=0)."""
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        """Serve on a daemon thread (for embedding / tests)."""
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="iaiops-metrics", daemon=True
        )
        self._thread.start()

    def serve_forever(self) -> None:
        """Serve on the calling thread (the CLI path)."""
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


__all__ = [
    "CONTENT_TYPE",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "GAUGE_NAME",
    "MetricsServer",
    "render_metrics",
]
