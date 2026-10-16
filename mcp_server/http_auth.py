"""Bearer-token authentication for the HTTP/SSE MCP transports.

The socket transports used to rely on an optional IP allowlist alone, while every
shipped container bound 0.0.0.0. Margo (rc.3) leaves workload-to-workload
authentication to the application, so the application does it here:

* ``IAIOPS_MCP_TOKEN`` (the value, injected from a secret facility) or
  ``IAIOPS_MCP_TOKEN_FILE`` (a path, e.g. a Docker/Podman secret) — never both;
* a **non-loopback bind without a token does not start** (fail closed — a
  warning is what the allowlist-only design did, and nobody reads warnings);
* when a token is configured it is required on every request, on any bind;
* a refused request is logged and written to the audit trail — at most one row
  per client per minute AND at most ``GLOBAL_ROWS_PER_WINDOW`` rows per minute in
  total (the suppressed count rides on the next row), so neither one client nor a
  client rotating source addresses can flood the trail and push real evidence
  out of retention; the request path is truncated;
* off loopback, FastMCP's DNS-rebinding Host check (which only knows loopback
  names) is replaced: ``IAIOPS_MCP_ALLOWED_HOSTS`` lists accepted Host headers,
  and without it the check is off — the bearer token is the control, and a
  rebinding page in a browser cannot present it.

Tokens are compared in constant time and never logged or audited.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TOKEN_ENV = "IAIOPS_MCP_TOKEN"
TOKEN_FILE_ENV = "IAIOPS_MCP_TOKEN_FILE"
ALLOWED_HOSTS_ENV = "IAIOPS_MCP_ALLOWED_HOSTS"
#: 32 characters of `openssl rand -base64 48` / `secrets.token_urlsafe(32)` is
#: far more than enough; anything shorter is usually a placeholder left in.
MIN_TOKEN_LENGTH = 32
#: One audit row per client IP per this many seconds of refusals.
AUDIT_WINDOW_S = 60.0
#: And never more than this many refusal rows per window across all clients.
GLOBAL_ROWS_PER_WINDOW = 10
#: Client addresses remembered for the per-client limit (oldest forgotten first).
MAX_TRACKED_CLIENTS = 1024
_MAX_AUDITED_PATH = 200

_CHALLENGE = 'Bearer realm="iaiops-mcp"'


def _transport_error(message: str) -> Exception:
    # Imported here: transport imports this module, and the error type lives there.
    from mcp_server.transport import TransportError

    return TransportError(message)


def is_loopback(host: str) -> bool:
    """True only for a literal loopback address or ``localhost``.

    A hostname other than ``localhost`` can resolve to anything, so it is not
    treated as loopback.
    """
    value = host.strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value.strip("[]")).is_loopback
    except ValueError:
        return False


def _read_token_file(path: str) -> str:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
        mode = file.stat().st_mode
    except OSError as exc:
        raise _transport_error(f"{TOKEN_FILE_ENV}={path} cannot be read: {exc}") from None
    if mode & 0o077:
        logger.warning(
            "%s=%s is readable by group or others (mode %o) — restrict it to the "
            "service user (chmod 600).",
            TOKEN_FILE_ENV,
            path,
            mode & 0o777,
        )
    return text


def _env(name: str) -> str | None:
    """A variable's value, with set-but-empty treated as unset (and said so)."""
    value = os.environ.get(name)
    if value is not None and not value.strip():
        logger.warning("%s is set but empty — treated as unset.", name)
        return None
    return value


def _check_token_text(token: str, source: str) -> str:
    if len(token) < MIN_TOKEN_LENGTH:
        raise _transport_error(
            f"The token from {source} is {len(token)} characters; at least "
            f"{MIN_TOKEN_LENGTH} are required. Generate one with: openssl rand -base64 48"
        )
    if not all(33 <= ord(ch) <= 126 for ch in token):
        raise _transport_error(
            f"The token from {source} must be printable ASCII without spaces — an HTTP "
            "header could never carry it intact. Generate one with: openssl rand -base64 48"
        )
    return token


def load_token() -> str | None:
    """The configured token, or None when neither variable is set (or both are empty).

    Raises:
        TransportError: both variables set, an unreadable file, or a token that is
            shorter than MIN_TOKEN_LENGTH or not printable ASCII.
    """
    raw_value = _env(TOKEN_ENV)
    raw_path = _env(TOKEN_FILE_ENV)
    if raw_value is not None and raw_path is not None:
        raise _transport_error(
            f"{TOKEN_ENV} and {TOKEN_FILE_ENV} are both set — set exactly one, so "
            "there is no question which token the server is enforcing."
        )
    if raw_value is None and raw_path is None:
        return None
    source = TOKEN_ENV if raw_value is not None else TOKEN_FILE_ENV
    token = (raw_value if raw_value is not None else _read_token_file(raw_path or "")).strip()
    return _check_token_text(token, source)


def require_token_for_bind(host: str, token: str | None) -> None:
    """Refuse to serve a non-loopback interface without a token (fail closed)."""
    if token is None and not is_loopback(host):
        raise _transport_error(
            f"Refusing to serve MCP on {host!r} without authentication. Set "
            f"{TOKEN_ENV} (or {TOKEN_FILE_ENV}) to a token of at least "
            f"{MIN_TOKEN_LENGTH} characters, injected from your secret store, and send "
            "it as 'Authorization: Bearer <token>'. To serve this host only, bind "
            "IAIOPS_MCP_HOST=127.0.0.1."
        )


def transport_security_for(host: str, token: str | None, allowed_hosts: str | None) -> Any:
    """FastMCP transport-security settings for this bind, or None for the SDK default.

    The SDK enables a DNS-rebinding Host check only for a loopback ``host`` given
    at construction, with loopback names; set later, off loopback, it rejects
    every real client with 421. ``allowed_hosts`` (comma-separated ``host:port``
    patterns, ``*`` for any port) turns the check on for those names.
    """
    if is_loopback(host):
        return None
    from mcp.server.transport_security import TransportSecuritySettings

    names = [h.strip() for h in (allowed_hosts or "").split(",") if h.strip()]
    if not names:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=names,
        allowed_origins=[f"http://{n}" for n in names] + [f"https://{n}" for n in names],
    )


def _presented_token(headers: Any) -> str:
    scheme, _, value = (headers.get("authorization") or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


class _RefusalAudit:
    """Audit rows for refused requests, bounded per client and in total."""

    def __init__(self, window_s: float = AUDIT_WINDOW_S) -> None:
        self._window_s = window_s
        self._last: OrderedDict[str, float] = OrderedDict()
        self._window_start = -window_s
        self._rows_in_window = 0
        self._suppressed = 0
        self._lock = threading.Lock()

    def tracked_clients(self) -> int:
        return len(self._last)

    def _admit(self, client_ip: str, now: float) -> int | None:
        """Under the lock: the suppressed count to report if a row is due, else None."""
        if now - self._window_start >= self._window_s:
            self._window_start, self._rows_in_window = now, 0
        recent = now - self._last.get(client_ip, -self._window_s) < self._window_s
        if recent or self._rows_in_window >= GLOBAL_ROWS_PER_WINDOW:
            self._suppressed += 1
            return None
        self._last[client_ip] = now
        self._last.move_to_end(client_ip)
        while len(self._last) > MAX_TRACKED_CLIENTS:
            self._last.popitem(last=False)
        self._rows_in_window += 1
        suppressed, self._suppressed = self._suppressed, 0
        return suppressed

    def record(self, client_ip: str, path: str) -> None:
        with self._lock:
            suppressed = self._admit(client_ip, time.monotonic())
        if suppressed is None:
            return
        logger.warning("MCP HTTP request refused (bad or missing token) from %s", client_ip)
        from iaiops.core.governance.audit import get_engine

        get_engine().log(
            skill="mcp-http",
            tool="mcp_http_auth",
            params={
                "client_ip": client_ip[:64],
                "path": path[:_MAX_AUDITED_PATH],
                "suppressed_since_last_row": suppressed,
            },
            status="denied",
            risk_level="low",
            rationale="bearer token missing or wrong — possible unauthorised access",
        )


def bearer_token_app(app: Any, token: str) -> Any:
    """Wrap a Starlette app so every request must carry ``Bearer <token>``."""
    import anyio
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    expected = token.encode("utf-8")
    audit = _RefusalAudit()

    async def _dispatch(request, call_next):
        presented = _presented_token(request.headers).encode("utf-8")
        if not hmac.compare_digest(presented, expected):
            client_ip = request.client.host if request.client else "unknown"
            # Off the event loop: the audit write is synchronous SQLite.
            await anyio.to_thread.run_sync(audit.record, client_ip, request.url.path)
            return JSONResponse(
                {"error": "unauthorized: missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": _CHALLENGE},
            )
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=_dispatch)
    return app


__all__ = [
    "ALLOWED_HOSTS_ENV",
    "AUDIT_WINDOW_S",
    "GLOBAL_ROWS_PER_WINDOW",
    "MAX_TRACKED_CLIENTS",
    "transport_security_for",
    "MIN_TOKEN_LENGTH",
    "TOKEN_ENV",
    "TOKEN_FILE_ENV",
    "bearer_token_app",
    "is_loopback",
    "load_token",
    "require_token_for_bind",
]
