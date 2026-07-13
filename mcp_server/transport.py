"""MCP transport selection — stdio (default) or a network-fronted HTTP/SSE transport.

iaiops has always spoken MCP over **stdio**. To let it sit **behind an HTTP gateway** (e.g. a
FastAPI front that does account/IP whitelisting) — the shape IGEL/Margo edge hosts ask for — this
adds an opt-in HTTP/SSE transport, selected by env:

    IAIOPS_MCP_TRANSPORT = stdio (default) | sse | streamable-http   (alias: http)
    IAIOPS_MCP_HOST      = bind host (default 127.0.0.1 — localhost only unless overridden)
    IAIOPS_MCP_PORT      = bind port (default 8000)

For the HTTP/SSE transports, if an IP allowlist is configured (``IAIOPS_ALLOWLIST_IPS``) it is
enforced by a small ASGI middleware (403 for non-allowed clients) — defense-in-depth for the
standalone case; account/token auth is best terminated at the gateway. stdio is unchanged.
"""

from __future__ import annotations

import logging
import os

from iaiops.core.governance.allowlist import load_allowlist_env

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
    mcp.settings.host = host
    mcp.settings.port = port
    app = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()

    allowlist = load_allowlist_env()
    if allowlist.restricts_ips:
        app = _ip_allowlist_app(app, allowlist)
        logger.info("IP allowlist active (%d network(s)).", len(allowlist.ip_networks))
    if host not in ("127.0.0.1", "localhost", "::1") and not allowlist.restricts_ips:
        logger.warning(
            "%s=%s exposes the MCP server on a non-loopback interface with NO IP allowlist — "
            "front it with a gateway or set IAIOPS_ALLOWLIST_IPS.",
            HOST_ENV,
            host,
        )

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
