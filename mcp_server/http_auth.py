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
  per client per minute, so a client hammering the port cannot flood the log.

Tokens are compared in constant time and never logged or audited.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TOKEN_ENV = "IAIOPS_MCP_TOKEN"
TOKEN_FILE_ENV = "IAIOPS_MCP_TOKEN_FILE"
#: 32 characters of `openssl rand -base64 48` / `secrets.token_urlsafe(32)` is
#: far more than enough; anything shorter is usually a placeholder left in.
MIN_TOKEN_LENGTH = 32
#: One audit row per client IP per this many seconds of refusals.
AUDIT_WINDOW_S = 60.0

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
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise _transport_error(f"{TOKEN_FILE_ENV}={path} cannot be read: {exc}") from None


def load_token() -> str | None:
    """The configured token, or None when neither variable is set.

    Raises:
        TransportError: both variables set, an unreadable file, or a token that
            is empty or shorter than MIN_TOKEN_LENGTH.
    """
    raw_value = os.environ.get(TOKEN_ENV)
    raw_path = os.environ.get(TOKEN_FILE_ENV)
    if raw_value is not None and raw_path is not None:
        raise _transport_error(
            f"{TOKEN_ENV} and {TOKEN_FILE_ENV} are both set — set exactly one, so "
            "there is no question which token the server is enforcing."
        )
    if raw_value is None and raw_path is None:
        return None
    source = TOKEN_ENV if raw_value is not None else TOKEN_FILE_ENV
    token = (raw_value if raw_value is not None else _read_token_file(raw_path or "")).strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise _transport_error(
            f"The token from {source} is {len(token)} characters; at least "
            f"{MIN_TOKEN_LENGTH} are required. Generate one with: openssl rand -base64 48"
        )
    return token


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


def _presented_token(headers: Any) -> str:
    scheme, _, value = (headers.get("authorization") or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


class _RefusalAudit:
    """Writes one audit row per client per window; counts the rest."""

    def __init__(self, window_s: float = AUDIT_WINDOW_S) -> None:
        self._window_s = window_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def record(self, client_ip: str, path: str) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last.get(client_ip, -self._window_s) < self._window_s:
                return
            self._last = {**self._last, client_ip: now}
        logger.warning("MCP HTTP request refused (bad or missing token) from %s", client_ip)
        from iaiops.core.governance.audit import get_engine

        get_engine().log(
            skill="mcp-http",
            tool="mcp_http_auth",
            params={"client_ip": client_ip, "path": path},
            status="denied",
            risk_level="low",
            rationale="bearer token missing or wrong — possible unauthorised access",
        )


def bearer_token_app(app: Any, token: str) -> Any:
    """Wrap a Starlette app so every request must carry ``Bearer <token>``."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    expected = token.encode("utf-8")
    audit = _RefusalAudit()

    async def _dispatch(request, call_next):
        presented = _presented_token(request.headers).encode("utf-8")
        if not hmac.compare_digest(presented, expected):
            client_ip = request.client.host if request.client else "unknown"
            audit.record(client_ip, request.url.path)
            return JSONResponse(
                {"error": "unauthorized: missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": _CHALLENGE},
            )
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=_dispatch)
    return app


__all__ = [
    "AUDIT_WINDOW_S",
    "MIN_TOKEN_LENGTH",
    "TOKEN_ENV",
    "TOKEN_FILE_ENV",
    "bearer_token_app",
    "is_loopback",
    "load_token",
    "require_token_for_bind",
]
