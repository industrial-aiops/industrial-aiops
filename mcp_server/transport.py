"""MCP transport selection — stdio (default) or a network-fronted HTTP/SSE transport.

iaiops has always spoken MCP over **stdio**. To let it sit **behind an HTTP gateway** (e.g. a
FastAPI front that does account/IP whitelisting) — the shape IGEL/Margo edge hosts ask for — this
adds an opt-in HTTP/SSE transport, selected by env:

    IAIOPS_MCP_TRANSPORT = stdio (default) | sse | streamable-http   (alias: http)
    IAIOPS_MCP_HOST      = bind host (default 127.0.0.1 — localhost only unless overridden)
    IAIOPS_MCP_PORT      = bind port (default 8000)

For the HTTP/SSE transports:

* a bearer token (``IAIOPS_MCP_TOKEN`` / ``IAIOPS_MCP_TOKEN_FILE``, see ``http_auth``) is
  required on every request when configured, and a **non-loopback bind without one refuses
  to start** — Margo leaves workload authentication to the application;
* an IP allowlist (``IAIOPS_ALLOWLIST_IPS``), when configured, is enforced first by a small
  ASGI middleware (403 for non-allowed clients) — a second layer, not the authentication.

stdio is unchanged.
"""

from __future__ import annotations

import logging
import os

from iaiops.core.governance.allowlist import load_allowlist_env
from mcp_server.http_auth import (
    ALLOWED_HOSTS_ENV,
    bearer_token_app,
    load_token,
    require_token_for_bind,
    transport_security_for,
)

logger = logging.getLogger(__name__)

TRANSPORT_ENV = "IAIOPS_MCP_TRANSPORT"
HOST_ENV = "IAIOPS_MCP_HOST"
PORT_ENV = "IAIOPS_MCP_PORT"

# Canonical transports + accepted aliases.
_ALIASES = {
    "stdio": "stdio",
    "sse": "sse",
    "streamable-http": "streamable-http",
    "http": "streamable-http",
}
VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


class TransportError(ValueError):
    """An unsupported IAIOPS_MCP_TRANSPORT value."""


def resolve_transport(value: str | None = None) -> str:
    """Resolve the requested transport to a canonical name (default 'stdio')."""
    raw = (value or os.environ.get(TRANSPORT_ENV) or "stdio").strip().lower()
    if raw not in _ALIASES:
        raise TransportError(
            f"Unknown {TRANSPORT_ENV}='{raw}'. "
            f"Supported: {', '.join(VALID_TRANSPORTS)} (alias: http)."
        )
    return _ALIASES[raw]


def _ip_allowlist_app(app, allowlist):
    """Wrap a Starlette app to 403 any client IP outside the allowlist."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    async def _dispatch(request, call_next):
        client_ip = request.client.host if request.client else None
        if not allowlist.ip_allowed(client_ip):
            return JSONResponse({"error": "forbidden: client IP not in allowlist"}, status_code=403)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=_dispatch)
    return app


def run_server(mcp) -> None:
    """Run ``mcp`` over the env-selected transport. stdio uses FastMCP directly; HTTP/SSE runs a
    (optionally IP-allowlisted) Starlette app under uvicorn."""
    transport = resolve_transport()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    host = os.environ.get(HOST_ENV, "127.0.0.1")
    port = int(os.environ.get(PORT_ENV, "8000"))
    # Before the app is built: a refused bind must not leave a half-started server.
    token = load_token()
    require_token_for_bind(host, token)
    if token is None:
        logger.warning(
            "MCP over %s on loopback WITHOUT a token: any local user or process can "
            "call the tools. Set IAIOPS_MCP_TOKEN to require one here too.",
            transport,
        )
    mcp.settings.host = host
    mcp.settings.port = port
    security = transport_security_for(host, token, os.environ.get(ALLOWED_HOSTS_ENV))
    if security is not None:
        mcp.settings.transport_security = security
    app = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()

    if token is not None:
        app = bearer_token_app(app, token)
        logger.info("Bearer-token authentication active.")
    # Added last = outermost: a client outside the allowlist is refused before the
    # token is even looked at.
    allowlist = load_allowlist_env()
    if allowlist.restricts_ips:
        app = _ip_allowlist_app(app, allowlist)
        logger.info("IP allowlist active (%d network(s)).", len(allowlist.ip_networks))

    import uvicorn

    logger.info("iaiops MCP over %s on http://%s:%d", transport, host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = [
    "resolve_transport",
    "run_server",
    "TransportError",
    "VALID_TRANSPORTS",
    "TRANSPORT_ENV",
    "HOST_ENV",
    "PORT_ENV",
]
