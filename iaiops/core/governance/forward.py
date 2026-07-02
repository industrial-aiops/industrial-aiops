"""Forward the audit log to an external SIEM as JSON lines (read-only egress).

Reads append-only rows from ``~/.iaiops/audit.db`` and emits each as one JSON
line to a **syslog (UDP)** collector or an **HTTP POST** endpoint. A persisted
*since-cursor* (the last forwarded ``id``) makes re-runs idempotent — a second
run forwards only rows written since the first, so nothing is duplicated.

This is egress of *governance metadata* the operator already owns, not a
control-system write: it only ever reads the audit DB and sends copies out.

Design rules honoured here:
  * Immutability — cursor state lives on disk, never mutated in place; the sink
    row→line transform returns a new dict.
  * Validate at the trust boundary — sink kind / host / URL scheme are checked
    before any socket is opened.
  * Never log secret/key material — audit rows carry tool params, so callers
    point the forwarder at a trusted collector; the module itself adds nothing.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from iaiops.core.governance.audit import AuditEngine, get_engine
from iaiops.core.governance.paths import ops_path

_log = logging.getLogger("iaiops.audit.forward")

_DEFAULT_SYSLOG_PORT = 514
_DEFAULT_HTTP_TIMEOUT = 10.0
_DEFAULT_FOLLOW_INTERVAL = 5.0
_MAX_BATCH = 5000
# syslog PRI = facility(user=1) * 8 + severity(informational=6) = 14
_SYSLOG_PRI = 14
_SYSLOG_MAX_BYTES = 65000  # keep a single UDP datagram well under the 64 KiB IPv4 limit
_CURSOR_FILE = "audit_forward.cursor"


# ── sink protocol + implementations ──────────────────────────────────────────


@runtime_checkable
class ForwardSink(Protocol):
    """A destination that accepts one JSON line at a time."""

    def send(self, line: str) -> None: ...

    def close(self) -> None: ...


class SyslogUDPSink:
    """Emit each JSON line as an RFC 3164-ish syslog datagram over UDP."""

    def __init__(self, host: str, port: int = _DEFAULT_SYSLOG_PORT) -> None:
        if not host:
            raise ValueError("syslog sink requires --host")
        self._addr = (host, int(port) or _DEFAULT_SYSLOG_PORT)
        # UDP datagram socket to a caller-specified collector. It only ever
        # sends (never binds/listens), so there is no bind-to-all exposure.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, line: str) -> None:
        payload = f"<{_SYSLOG_PRI}>iaiops-audit: {line}".encode("utf-8", "replace")
        self._sock.sendto(payload[:_SYSLOG_MAX_BYTES], self._addr)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class HttpSink:
    """POST each JSON line to an HTTP(S) endpoint (one request per row)."""

    def __init__(self, url: str, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        self._url = url
        self._timeout = timeout

    def send(self, line: str) -> None:
        request = urllib.request.Request(
            self._url,
            data=line.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        # URL scheme is validated to http/https in _http_url (no file:/ftp:
        # local-resource read), so urlopen here cannot reach the filesystem.
        with urllib.request.urlopen(request, timeout=self._timeout):  # nosec B310
            pass

    def close(self) -> None:
        pass


def _http_url(host: str, port: int, path: str) -> str:
    """Build and validate an http/https POST URL from CLI parts.

    ``host`` may be a bare host or a full URL; only http/https are accepted so
    the resulting :class:`HttpSink` can never be pointed at a local file.
    """
    if not host:
        raise ValueError("http sink requires --host (host or base URL)")
    raw = host if "://" in host else f"http://{host}"
    parsed = urllib.parse.urlparse(raw)
    scheme = (parsed.scheme or "http").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"http sink requires an http/https URL, got scheme {scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"http sink could not parse a host from {host!r}")
    resolved_port = int(port) or parsed.port or (443 if scheme == "https" else 80)
    request_path = path or parsed.path or "/"
    return urllib.parse.urlunparse((scheme, f"{hostname}:{resolved_port}", request_path, "", "", ""))


def build_sink(kind: str, *, host: str, port: int = 0, path: str = "/") -> ForwardSink:
    """Construct a forward sink from validated CLI inputs."""
    resolved = (kind or "").strip().lower()
    if resolved == "syslog":
        return SyslogUDPSink(host, port or _DEFAULT_SYSLOG_PORT)
    if resolved == "http":
        return HttpSink(_http_url(host, port, path))
    raise ValueError(f"Unknown sink {kind!r}. Use 'syslog' or 'http'.")


# ── cursor persistence ───────────────────────────────────────────────────────


def _default_cursor_path() -> Path:
    return ops_path(_CURSOR_FILE)


def read_cursor(path: Path) -> int:
    """Return the last forwarded row id (0 when no cursor exists / is unreadable)."""
    try:
        text = path.read_text("utf-8").strip()
    except OSError:
        return 0
    try:
        return max(0, int(text))
    except ValueError:
        _log.warning("Corrupt forward cursor at %s; restarting from 0", path)
        return 0


def write_cursor(path: Path, value: int) -> None:
    """Atomically persist the cursor (write-temp-then-rename)."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(str(int(value)), "utf-8")
    tmp.replace(path)


# ── row → JSON line ──────────────────────────────────────────────────────────


def row_to_line(row: dict[str, Any]) -> str:
    """Serialize one audit row to a single JSON line.

    ``params``/``result`` are stored as JSON *text*; re-parse them so the emitted
    line is proper nested JSON rather than an escaped string. Returns a new dict
    (the input row is not mutated).
    """
    out = dict(row)
    for field in ("params", "result"):
        value = out.get(field)
        if isinstance(value, str):
            try:
                out[field] = json.loads(value)
            except ValueError:
                pass  # leave as raw text if it is not valid JSON
    return json.dumps(out, ensure_ascii=False, default=str)


# ── forwarding ───────────────────────────────────────────────────────────────


def forward_audit(
    sink: ForwardSink,
    *,
    engine: AuditEngine | None = None,
    cursor_path: Path | None = None,
    since: str | None = None,
    limit: int = _MAX_BATCH,
) -> dict[str, Any]:
    """Forward every audit row newer than the cursor to ``sink`` exactly once.

    Rows are read in ascending id order, sent one JSON line each, and the cursor
    is advanced to the max id sent (persisted only when at least one row went
    out, so a failed send leaves the cursor untouched for a clean retry).
    """
    engine = engine or get_engine()
    cursor_path = cursor_path or _default_cursor_path()
    start = read_cursor(cursor_path)
    rows = engine.rows_after(start, since=since, limit=limit)

    sent = 0
    last_id = start
    for row in rows:
        sink.send(row_to_line(row))
        sent += 1
        last_id = max(last_id, int(row.get("id", last_id)))

    if sent:
        write_cursor(cursor_path, last_id)
    return {"forwarded": sent, "from_cursor": start, "cursor": last_id}


def forward_follow(
    sink: ForwardSink,
    *,
    engine: AuditEngine | None = None,
    cursor_path: Path | None = None,
    since: str | None = None,
    interval: float = _DEFAULT_FOLLOW_INTERVAL,
    max_cycles: int | None = None,
) -> dict[str, Any]:
    """Poll-and-forward in a loop until ``max_cycles`` (``None`` = run forever).

    The first pass may honour ``since``; after that the cursor takes over so no
    row is ever re-sent. ``max_cycles`` exists for tests / bounded runs.
    """
    total = 0
    cycles = 0
    floor = since
    while max_cycles is None or cycles < max_cycles:
        result = forward_audit(sink, engine=engine, cursor_path=cursor_path, since=floor)
        total += int(result["forwarded"])
        floor = None  # cursor governs subsequent passes
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(interval)
    return {"forwarded": total, "cycles": cycles}


__all__ = [
    "ForwardSink",
    "SyslogUDPSink",
    "HttpSink",
    "build_sink",
    "read_cursor",
    "write_cursor",
    "row_to_line",
    "forward_audit",
    "forward_follow",
]
