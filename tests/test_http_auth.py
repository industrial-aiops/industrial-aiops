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


def test_an_empty_token_is_refused_rather_than_read_as_unset(monkeypatch):
    """`IAIOPS_MCP_TOKEN=` is someone trying to set one — not a request for no auth."""
    monkeypatch.setenv(TOKEN_ENV, "   ")
    with pytest.raises(TransportError):
        load_token()


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
