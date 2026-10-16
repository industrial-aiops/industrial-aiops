"""Bearer-token auth on the HTTP/SSE transports — and the bind it refuses.

Before this, the HTTP transport had only an optional IP allowlist, and every
shipped container (Margo package, airgap, Siemens IE, IGEL) bound 0.0.0.0. Margo
rc.3 leaves workload-to-workload authentication to the application, so the
application does it: a non-loopback bind without a token does not start.
"""

from __future__ import annotations

import pytest

from mcp_server.http_auth import (
    MIN_TOKEN_LENGTH,
    TOKEN_ENV,
    TOKEN_FILE_ENV,
    bearer_token_app,
    is_loopback,
    load_token,
    require_token_for_bind,
)
from mcp_server.transport import TransportError

pytestmark = pytest.mark.unit

GOOD = "t" * MIN_TOKEN_LENGTH


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(TOKEN_FILE_ENV, raising=False)
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    from iaiops.core.governance.audit import reset_engine

    reset_engine()
    yield
    reset_engine()


# ─── which binds need a token ────────────────────────────────────────────────


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2", " LOCALHOST "])
def test_loopback_hosts(host):
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.0.0.5", "192.168.1.10", "iaiops.plant"])
def test_non_loopback_hosts(host):
    """A hostname is not loopback: it can resolve to anything, so it needs a token."""
    assert not is_loopback(host)


def test_a_non_loopback_bind_without_a_token_refuses_to_start():
    with pytest.raises(TransportError) as exc:
        require_token_for_bind("0.0.0.0", None)
    message = str(exc.value)
    assert TOKEN_ENV in message and TOKEN_FILE_ENV in message


def test_a_loopback_bind_without_a_token_is_allowed():
    require_token_for_bind("127.0.0.1", None)


def test_a_non_loopback_bind_with_a_token_is_allowed():
    require_token_for_bind("0.0.0.0", GOOD)


# ─── where the token comes from ──────────────────────────────────────────────


def test_no_token_configured():
    assert load_token() is None


def test_token_from_env(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, f"  {GOOD}\n")
    assert load_token() == GOOD


def test_token_from_file(monkeypatch, tmp_path):
    secret = tmp_path / "token"
    secret.write_text(GOOD + "\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_FILE_ENV, str(secret))
    assert load_token() == GOOD


def test_both_sources_is_refused_not_ranked(monkeypatch, tmp_path):
    secret = tmp_path / "token"
    secret.write_text(GOOD, encoding="utf-8")
    monkeypatch.setenv(TOKEN_FILE_ENV, str(secret))
    monkeypatch.setenv(TOKEN_ENV, GOOD)
    with pytest.raises(TransportError, match="both"):
        load_token()


def test_an_unreadable_token_file_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(TOKEN_FILE_ENV, str(tmp_path / "missing"))
    with pytest.raises(TransportError, match="cannot be read"):
        load_token()


def test_a_short_token_is_refused(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "short")
    with pytest.raises(TransportError, match=str(MIN_TOKEN_LENGTH)):
        load_token()


def test_an_empty_token_variable_counts_as_unset(monkeypatch, caplog):
    """Compose files pass `${IAIOPS_MCP_TOKEN:-}`: empty must not block the file route.

    Off loopback, unset still means "refuse to start", so this cannot open a hole.
    """
    import logging

    monkeypatch.setenv(TOKEN_ENV, "   ")
    with caplog.at_level(logging.WARNING):
        assert load_token() is None
    assert TOKEN_ENV in caplog.text
    with pytest.raises(TransportError):
        require_token_for_bind("0.0.0.0", load_token())


def test_an_empty_token_variable_beside_a_token_file_uses_the_file(monkeypatch, tmp_path):
    secret = tmp_path / "token"
    secret.write_text(GOOD, encoding="utf-8")
    secret.chmod(0o600)
    monkeypatch.setenv(TOKEN_ENV, "")
    monkeypatch.setenv(TOKEN_FILE_ENV, str(secret))
    assert load_token() == GOOD


@pytest.mark.parametrize("bad", ["é" * 40, "tab\there" + "x" * 32, "space here" + "x" * 32])
def test_a_token_that_cannot_survive_an_http_header_is_refused(monkeypatch, bad):
    """Headers arrive as latin-1; a non-ASCII or spaced token could never match."""
    monkeypatch.setenv(TOKEN_ENV, bad)
    with pytest.raises(TransportError, match="printable ASCII"):
        load_token()


def test_a_world_readable_token_file_is_warned_about(monkeypatch, tmp_path, caplog):
    import logging

    secret = tmp_path / "token"
    secret.write_text(GOOD, encoding="utf-8")
    secret.chmod(0o644)
    monkeypatch.setenv(TOKEN_FILE_ENV, str(secret))
    with caplog.at_level(logging.WARNING):
        assert load_token() == GOOD
    assert "readable" in caplog.text


# ─── the middleware ──────────────────────────────────────────────────────────


class _Client:
    """Drives the wrapped ASGI app in-process (no socket, no TestClient)."""

    def __init__(self, app) -> None:
        self._app = app

    def post(self, path: str, headers: dict[str, str] | None = None):
        import anyio
        import httpx

        async def _go():
            transport = httpx.ASGITransport(app=self._app, client=("10.1.2.3", 5555))
            async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
                return await c.post(path, headers=headers or {})

        return anyio.run(_go)


def _client(token: str = GOOD) -> _Client:
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def ok(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"])])
    return _Client(bearer_token_app(app, token))


def test_a_request_without_a_token_gets_401_with_a_challenge():
    response = _client().post("/mcp")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize(
    "header",
    [f"Bearer {GOOD}x", f"bearer {GOOD[:-1]}", f"Basic {GOOD}", GOOD, "Bearer "],
)
def test_a_wrong_token_gets_401(header):
    assert _client().post("/mcp", headers={"Authorization": header}).status_code == 401


def test_the_right_token_passes():
    response = _client().post("/mcp", headers={"Authorization": f"Bearer {GOOD}"})
    assert response.status_code == 200
    assert response.text == "ok"


def test_the_scheme_is_case_insensitive():
    response = _client().post("/mcp", headers={"Authorization": f"bearer {GOOD}"})
    assert response.status_code == 200


def test_a_refusal_is_written_to_the_audit_trail():
    """CRA Annex I Part I(2)(d): report on possible unauthorised access."""
    from iaiops.core.governance.audit import get_engine

    _client().post("/mcp", headers={"Authorization": "Bearer nope"})
    rows = [r for r in get_engine().query(limit=50) if r["tool"] == "mcp_http_auth"]
    assert rows, "a refused request left no audit row"
    assert rows[0]["status"] == "denied"
    assert GOOD not in str(rows[0]) and "nope" not in str(rows[0])


def test_a_flood_of_refusals_does_not_flood_the_audit_trail():
    from iaiops.core.governance.audit import get_engine

    client = _client()
    for _ in range(25):
        client.post("/mcp")
    rows = [r for r in get_engine().query(limit=100) if r["tool"] == "mcp_http_auth"]
    assert len(rows) == 1, "one client hammering the port wrote one row per request"


def test_a_huge_path_is_truncated_in_the_audit_row():
    from iaiops.core.governance.audit import get_engine

    _client().post("/mcp" + "A" * 5000)
    rows = [r for r in get_engine().query(limit=50) if r["tool"] == "mcp_http_auth"]
    assert len(rows[0]["params"]) < 600


def test_refusals_from_many_addresses_are_capped_globally():
    """Rotating source addresses must not buy one audit row each."""
    from iaiops.core.governance.audit import get_engine
    from mcp_server.http_auth import GLOBAL_ROWS_PER_WINDOW, _RefusalAudit

    audit = _RefusalAudit()
    for n in range(200):
        audit.record(f"2001:db8::{n:x}", "/mcp")
    rows = [r for r in get_engine().query(limit=500) if r["tool"] == "mcp_http_auth"]
    assert len(rows) == GLOBAL_ROWS_PER_WINDOW
    assert audit.tracked_clients() <= 1024


# ─── host checking off loopback ──────────────────────────────────────────────


def test_off_loopback_without_allowed_hosts_disables_the_host_check():
    """The token is the control; a DNS-rebinding page cannot present it."""
    from mcp_server.http_auth import transport_security_for

    settings = transport_security_for("0.0.0.0", GOOD, None)
    assert settings.enable_dns_rebinding_protection is False


def test_off_loopback_with_allowed_hosts_checks_them():
    from mcp_server.http_auth import transport_security_for

    settings = transport_security_for("0.0.0.0", GOOD, "iaiops:*, 10.0.0.5:8000")
    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ["iaiops:*", "10.0.0.5:8000"]


def test_loopback_keeps_the_sdk_default():
    from mcp_server.http_auth import transport_security_for

    assert transport_security_for("127.0.0.1", None, None) is None


def test_a_token_server_answers_a_non_loopback_host_header(monkeypatch):
    """The 421 the review found: Host: 10.0.0.5 with a correct token must get through."""
    from mcp.server.fastmcp import FastMCP

    from mcp_server.http_auth import transport_security_for

    server = FastMCP(
        "t", host="0.0.0.0", transport_security=transport_security_for("0.0.0.0", GOOD, None)
    )
    app = bearer_token_app(server.streamable_http_app(), GOOD)

    import anyio
    import httpx

    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=transport, base_url="http://10.0.0.5:8000") as c:
                return await c.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "t", "version": "1"},
                        },
                    },
                    headers={
                        "Authorization": f"Bearer {GOOD}",
                        "Accept": "application/json, text/event-stream",
                    },
                )

    response = anyio.run(_go)
    assert response.status_code == 200, (response.status_code, response.text[:200])
