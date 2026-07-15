"""Forward the audit log to an external SIEM as JSON lines (read-only egress).

Reads append-only rows from ``~/.iaiops/audit.db`` and emits each as one JSON
line to a **syslog (UDP)** collector or an **HTTP POST** endpoint. A persisted
*since-cursor* (the last forwarded ``id``) makes re-runs incremental — a second
run forwards only rows written since the last successful send. Delivery is
at-least-once: on a mid-batch failure the cursor keeps the rows already sent, so
retry resumes after them (only the failing row may be re-sent; none are lost).

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
import os
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
        _log.warning(
            "SIEM forward over UDP syslog to %s is PLAINTEXT — audit rows "
            "(tool params, endpoints) cross the network unencrypted. Prefer an "
            "https collector, or keep this on a trusted management network.",
            host,
        )
        self._addr = (host, int(port) or _DEFAULT_SYSLOG_PORT)
        # UDP datagram socket to a caller-specified collector. It only ever
        # sends (never binds/listens), so there is no bind-to-all exposure.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, line: str) -> None:
        self._sock.sendto(_syslog_payload(line), self._addr)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError as exc:
            _log.debug("Error closing syslog socket: %s", exc)


class HttpSink:
    """POST each JSON line to an HTTP(S) endpoint (one request per row).

    Optional token auth: set ``IAIOPS_FORWARD_TOKEN`` (or pass ``token=``).
    The header shape is configurable for non-Bearer SIEMs:

    * ``IAIOPS_FORWARD_AUTH_SCHEME`` (default ``Bearer``) — the scheme prefix,
      e.g. ``Splunk`` (HEC) or ``ApiKey`` (Elastic). Empty string → the raw
      token becomes the header value (``X-Api-Key``-style headers).
    * ``IAIOPS_FORWARD_AUTH_HEADER`` (default ``Authorization``) — the header
      name, e.g. ``X-Api-Key``.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = _DEFAULT_HTTP_TIMEOUT,
        token: str | None = None,
        auth_scheme: str | None = None,
        auth_header: str | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._token = token if token is not None else os.environ.get("IAIOPS_FORWARD_TOKEN", "")
        self._auth_scheme = (
            auth_scheme
            if auth_scheme is not None
            else os.environ.get("IAIOPS_FORWARD_AUTH_SCHEME", "Bearer")
        ).strip()
        self._auth_header = (
            auth_header
            if auth_header is not None
            else os.environ.get("IAIOPS_FORWARD_AUTH_HEADER", "Authorization")
        ).strip() or "Authorization"
        if url.lower().startswith("http://"):
            _log.warning(
                "SIEM forward endpoint %s is PLAINTEXT http — audit rows (tool "
                "params, endpoints%s) cross the network unencrypted. Use https.",
                url,
                " and the bearer token" if self._token else "",
            )

    def send(self, line: str) -> None:
        headers = {"Content-Type": "application/json"}
        if self._token:
            value = f"{self._auth_scheme} {self._token}" if self._auth_scheme else self._token
            headers[self._auth_header] = value
        request = urllib.request.Request(
            self._url,
            data=line.encode("utf-8"),
            method="POST",
            headers=headers,
        )
        # URL scheme is validated to http/https in _http_url (no file:/ftp:
        # local-resource read), so urlopen here cannot reach the filesystem.
        with urllib.request.urlopen(request, timeout=self._timeout):  # nosec B310
            pass

    def close(self) -> None:
        pass


_SYSLOG_PREFIX = f"<{_SYSLOG_PRI}>iaiops-audit: "


def _syslog_payload(line: str) -> bytes:
    """Frame a JSON line as a syslog datagram that fits one UDP packet.

    Oversized records are shrunk field-by-field (params first — it carries the
    bulk) and marked ``"_truncated": true`` so the emitted line stays valid
    JSON at the collector. A raw byte cut would silently corrupt the record.
    """
    payload = f"{_SYSLOG_PREFIX}{line}".encode("utf-8", "replace")
    if len(payload) <= _SYSLOG_MAX_BYTES:
        return payload
    budget = _SYSLOG_MAX_BYTES - len(_SYSLOG_PREFIX.encode("utf-8"))
    return f"{_SYSLOG_PREFIX}{_shrink_line(line, budget)}".encode("utf-8", "replace")


def _shrink_line(line: str, budget: int) -> str:
    """Shrink an oversized JSON line to ``budget`` bytes, keeping it valid JSON."""
    try:
        record = json.loads(line)
    except ValueError:
        record = None
    if not isinstance(record, dict):
        # Not a JSON object — nothing structural to preserve; cut on a UTF-8
        # boundary (never split a multibyte char).
        return line.encode("utf-8")[:budget].decode("utf-8", "ignore")
    for field in ("params", "result", "rationale"):
        if field not in record:
            continue
        record = {**record, field: "[dropped: oversized]", "_truncated": True}
        candidate = json.dumps(record, ensure_ascii=False, default=str)
        if len(candidate.encode("utf-8")) <= budget:
            return candidate
    # Still oversized after dropping the bulk fields — emit a minimal, valid
    # envelope so the collector can at least correlate by id / tool / status.
    minimal = {
        "id": record.get("id"),
        "ts": record.get("ts"),
        "tool": record.get("tool"),
        "status": record.get("status"),
        "_truncated": True,
    }
    return json.dumps(minimal, ensure_ascii=False, default=str)


def _http_url(host: str, port: int, path: str) -> str:
    """Build and validate an http/https POST URL from CLI parts.

    ``host`` may be a bare host or a full URL; only http/https are accepted so
    the resulting :class:`HttpSink` can never be pointed at a local file.
    A bare host defaults to **https** — pass an explicit ``http://`` URL to
    opt into plaintext (loudly warned).
    """
    if not host:
        raise ValueError("http sink requires --host (host or base URL)")
    raw = host if "://" in host else f"https://{host}"
    parsed = urllib.parse.urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"http sink requires an http/https URL, got scheme {scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"http sink could not parse a host from {host!r}")
    resolved_port = int(port) or parsed.port or (443 if scheme == "https" else 80)
    request_path = path or parsed.path or "/"
    return urllib.parse.urlunparse(
        (scheme, f"{hostname}:{resolved_port}", request_path, "", "", "")
    )


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

    Rows are read in ascending id order and sent one JSON line each. Delivery is
    **at-least-once**: the cursor is advanced (in a ``finally``) to the max id
    that was successfully sent, so a mid-batch send failure resumes on the next
    run after the last delivered row — only the row that failed can be re-sent, no
    rows are skipped.
    """
    engine = engine or get_engine()
    cursor_path = cursor_path or _default_cursor_path()
    start = read_cursor(cursor_path)
    rows = engine.rows_after(start, since=since, limit=limit)

    sent = 0
    last_id = start
    try:
        for row in rows:
            sink.send(row_to_line(row))
            sent += 1
            last_id = max(last_id, int(row.get("id", last_id)))
    finally:
        # Persist progress for rows that DID go out, even if a later send raised,
        # so retry doesn't re-deliver the whole batch (at-least-once, not lost).
        if last_id > start:
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
