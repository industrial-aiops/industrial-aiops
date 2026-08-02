"""The MCP server over its NETWORK transports, driven by a real MCP client.

`test_mcp_stdio_live.py` took the stdio path to rung 2a and said what it left:
"the opt-in HTTP/SSE transport (`IAIOPS_MCP_TRANSPORT`)". That transport is not
a formality — it is the shape edge hosts ask for (`deploy/margo`, the IGEL
submission), it runs a Starlette app under uvicorn instead of FastMCP's own
loop, and it carries **a security control that exists nowhere else**: the IP
allowlist middleware that 403s a client outside `IAIOPS_ALLOWLIST_IPS`.

Both halves matter, and each needs a real socket:

* a `streamable-http` and an `sse` server that a third-party client can
  initialise, list tools on and call a tool through — the same rung-2a claim
  stdio has, on the transports an operator actually exposes;
* the allowlist, seen from a client that is NOT on the list. Asserting it
  against the middleware in-process would assume the wiring under test.

Not covered: TLS termination, an authenticating gateway in front (the design
puts account auth there deliberately), and clients other than the reference SDK.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed")
pytest.importorskip("uvicorn", reason="uvicorn not installed — HTTP transports need it")

from mcp import ClientSession  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

_PROFILE = "modbus"  # small, pure-python, and carries a governed write
_STARTUP_TIMEOUT_S = 30.0


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Server:
    """The real entrypoint, run as a subprocess over a network transport."""

    def __init__(self, transport: str, port: int, proc: subprocess.Popen[str]) -> None:
        self.transport = transport
        self.port = port
        self.proc = proc

    @property
    def url(self) -> str:
        leaf = "sse" if self.transport == "sse" else "mcp"
        return f"http://127.0.0.1:{self.port}/{leaf}"


def _start(transport: str, tmp_path, **env: str) -> Iterator[_Server]:
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", "from mcp_server.server import main; main()"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={
            **os.environ,
            "IAIOPS_MCP": _PROFILE,
            "IAIOPS_HOME": str(tmp_path),
            "IAIOPS_MCP_TRANSPORT": transport,
            "IAIOPS_MCP_HOST": "127.0.0.1",
            "IAIOPS_MCP_PORT": str(port),
            **env,
        },
    )
    try:
        _wait_until_listening(proc, port)
        yield _Server(transport, port, proc)
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _wait_until_listening(proc: subprocess.Popen[str], port: int) -> None:
    """Wait for the port, and FAIL loudly with the child's output if it dies.

    A server that exits during startup must not become a green skip: on these
    transports that would mean uvicorn or Starlette is missing or the app failed
    to build, which is a product problem, not an environmental one.
    """
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"MCP server exited during startup:\n{output[-2000:]}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.fail(f"MCP server did not listen on {port} within {_STARTUP_TIMEOUT_S:g}s")


@pytest.fixture
def http_server(tmp_path) -> Iterator[_Server]:
    yield from _start("streamable-http", tmp_path)


@pytest.fixture
def sse_server(tmp_path) -> Iterator[_Server]:
    yield from _start("sse", tmp_path)


@pytest.fixture
def blocked_server(tmp_path) -> Iterator[_Server]:
    """A server whose IP allowlist deliberately excludes this client (loopback)."""
    yield from _start("streamable-http", tmp_path, IAIOPS_ALLOWLIST_IPS="10.99.0.0/24")


async def _tool_names(session: ClientSession) -> set[str]:
    return {tool.name for tool in (await session.list_tools()).tools}


async def test_streamable_http_serves_a_real_mcp_session(http_server: _Server) -> None:
    """Initialise, list and call — over HTTP, through the SDK's own client.

    The tool call targets an unreachable endpoint on purpose: what is being
    proven is that a *connector failure* comes back as readable content over
    this transport too, rather than a protocol error that kills the session —
    the same promise the stdio test pins, on the transport that has a proxy,
    a chunked body and a session header in the way.
    """
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(http_server.url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()

            names = await _tool_names(session)
            assert "modbus_read_holding" in names, sorted(names)[:20]

            result = await session.call_tool(
                "modbus_read_holding",
                {"endpoint": "nope", "address": 0, "count": 1},
            )
            assert result.content, result
            assert not result.isError, "a connector failure killed the JSON-RPC call"

            # The session survives the failed call and can still be used.
            assert await _tool_names(session) == names


async def test_sse_transport_serves_a_real_mcp_session(sse_server: _Server) -> None:
    """The `sse` transport is a different Starlette app — it needs its own proof.

    `mcp.sse_app()` and `mcp.streamable_http_app()` are separate constructions,
    and `resolve_transport` picking one is not evidence the other works.
    """
    from mcp.client.sse import sse_client

    async with sse_client(sse_server.url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert "modbus_read_holding" in await _tool_names(session)


async def test_the_ip_allowlist_refuses_a_client_outside_it(blocked_server: _Server) -> None:
    """403 before any MCP conversation happens — the control's whole purpose.

    This middleware only exists on the HTTP/SSE path, so nothing that ran before
    today could show it doing anything. The request is made with a plain HTTP
    client rather than the MCP one: the point is that the refusal arrives as an
    HTTP status, from the middleware, before the protocol is reached.
    """
    import httpx

    response = httpx.post(
        blocked_server.url,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
        timeout=10,
    )

    assert response.status_code == 403, (
        f"the allowlist let a non-allowed client through: {response.status_code} "
        f"{response.text[:200]}"
    )
    assert "forbidden" in response.text.lower(), response.text[:200]


async def test_the_allowlist_is_off_by_default(http_server: _Server) -> None:
    """The control must not be load-bearing by accident.

    If an unconfigured server also 403'd, the test above would pass for the wrong
    reason and the transport would be broken for every ordinary operator.
    """
    import httpx

    response = httpx.post(
        http_server.url,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
        timeout=10,
    )

    assert response.status_code != 403, response.text[:200]
