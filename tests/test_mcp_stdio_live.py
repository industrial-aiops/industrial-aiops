"""The MCP server, driven by a REAL MCP client over stdio.

Every other test in this repo calls tool functions directly in-process. That leaves
the product's **primary interface** unexercised: the stdio transport, the JSON-RPC
framing, `list_tools()` on the wire, argument and result serialisation, and — the
two that carry product promises —

* **the `ToolAnnotations` a client actually receives.** 0.20.1's whole point is that
  a client can tell a plant write from a browse *programmatically*. Until now that
  was verified against the in-process registry, which is not where a client looks;
* **what `IAIOPS_NO_EGRESS=1` withholds, as seen from outside.** The airgap promise
  is "the data-shipping tools do not appear in `list_tools()`". Asserting it against
  our own registry assumes the thing under test — that the registry is what the
  client sees.

The client here is the `mcp` SDK's own `stdio_client` + `ClientSession`, launching
the real `mcp_server.server:main` entrypoint as a subprocess with the same env vars
an operator would set. Rung **2a**: a third-party implementation of the protocol
judges our server.

Not covered: the opt-in HTTP/SSE transport (`IAIOPS_MCP_TRANSPORT`), and any client
other than the reference SDK.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

# A small, dependency-light profile: the brain plus one pure-python protocol. Big
# enough to carry a destructive tool and the egress tools, small enough to start fast.
_PROFILE = "modbus"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def _session(**env: str) -> AsyncIterator[ClientSession]:
    """Launch the real server entrypoint over stdio and hand back a live session."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from mcp_server.server import main; main()"],
        env={
            **os.environ,
            "IAIOPS_MCP": _PROFILE,
            # Keep the child off the developer's real home directory.
            "IAIOPS_HOME": os.environ.get("PYTEST_IAIOPS_HOME", os.environ.get("TMPDIR", "/tmp")),
            **env,
        },
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def _tool_names(session: ClientSession) -> set[str]:
    return {tool.name for tool in (await session.list_tools()).tools}


def _find(tools: list[Any], name: str) -> Any:
    return next((tool for tool in tools if tool.name == name), None)


# ─── the transport itself ────────────────────────────────────────────────────


async def test_a_real_client_can_initialize_and_list_tools() -> None:
    """The handshake and `list_tools()` over actual stdio JSON-RPC — the path every
    user takes, and the one nothing exercised before."""
    async with _session() as session:
        names = await _tool_names(session)
        assert names, "the server exposed no tools to a real client"
        assert "modbus_read_holding" in names, f"profile {_PROFILE!r} tools missing"
        assert "protocols_supported" in names, "the discovery tool is not exposed"


async def test_a_tool_call_round_trips_through_json_rpc() -> None:
    """Arguments in, structured result out, over the wire. A pure-analysis tool, so
    the assertion is about serialisation rather than any device."""
    async with _session() as session:
        result = await session.call_tool("modbus_list_templates", {})
        assert not result.isError, f"call failed: {result.content}"
        assert result.content, "no content came back"


async def test_a_tool_error_arrives_as_content_not_a_protocol_crash() -> None:
    """A connector failure must reach the client as a tool result it can read — the
    canonical `{error, hint}` envelope — not as a JSON-RPC transport error that
    kills the session."""
    async with _session() as session:
        result = await session.call_tool(
            "modbus_read_holding", {"endpoint": "definitely-not-configured", "address": 0}
        )
        text = " ".join(getattr(c, "text", "") for c in result.content)
        assert text.strip(), "the failure carried no message for the client"
        # The session must still be usable afterwards.
        assert await _tool_names(session)


# ─── the annotations a client actually receives ──────────────────────────────


async def test_annotations_reach_the_client(anyio_backend: str) -> None:
    """0.20.1's promise, verified where it is consumed rather than where it is made.

    A client must be able to tell a plant write from a browse without parsing the
    `[READ]`/`[WRITE]` docstring tag.
    """
    async with _session() as session:
        tools = (await session.list_tools()).tools

        read = _find(tools, "modbus_read_holding")
        assert read is not None and read.annotations is not None, (
            "a read tool arrived at the client with no annotations"
        )
        assert read.annotations.readOnlyHint is True
        assert read.annotations.destructiveHint is False

        annotated = [t for t in tools if t.annotations is not None]
        assert len(annotated) == len(tools), (
            f"{len(tools) - len(annotated)} tool(s) reached the client unannotated"
        )


async def test_a_destructive_tool_is_flagged_destructive_to_the_client() -> None:
    """The one that matters for a confirm prompt. `mqtt_publish` is high-risk and
    commands a live system; a client must see that without knowing any OT."""
    async with _session(IAIOPS_MCP="sparkplug") as session:
        tools = (await session.list_tools()).tools
        publish = _find(tools, "mqtt_publish")
        assert publish is not None, "mqtt_publish not exposed by the sparkplug profile"
        assert publish.annotations is not None
        assert publish.annotations.destructiveHint is True
        assert publish.annotations.readOnlyHint is False


# ─── the airgap promise, from outside ────────────────────────────────────────


async def test_no_egress_withholds_the_data_shipping_tools_from_a_real_client() -> None:
    """The airgap posture is a claim about what a CLIENT can see. Asserting it
    against our own registry assumes the thing under test; this asks the client.
    """
    async with _session(IAIOPS_MCP="sparkplug") as session:
        with_egress = await _tool_names(session)

    async with _session(IAIOPS_MCP="sparkplug", IAIOPS_NO_EGRESS="1") as session:
        sealed = await _tool_names(session)

    withheld = with_egress - sealed
    assert withheld, "IAIOPS_NO_EGRESS withheld nothing the client could see"
    assert "mqtt_publish" in withheld, (
        f"mqtt_publish still visible to a sealed-site client; withheld={sorted(withheld)}"
    )
    assert sealed < with_egress, "the sealed surface is not a strict subset"
    # The reads must survive — the gate is about shipping data OUT, not about
    # turning the tap off.
    assert "uns_topic_audit" in sealed, "a read tool was withheld by the egress gate"


# ─── profile selection through the real entrypoint ───────────────────────────


async def test_the_profile_env_var_selects_the_surface() -> None:
    """`IAIOPS_MCP` is how an operator picks a surface. Two profiles must expose
    genuinely different tools — through the real entrypoint, not a test helper."""
    async with _session(IAIOPS_MCP="modbus") as session:
        modbus = await _tool_names(session)
    async with _session(IAIOPS_MCP="s7") as session:
        s7 = await _tool_names(session)

    assert any(name.startswith("modbus_") for name in modbus)
    assert not any(name.startswith("s7_") for name in modbus), "the modbus profile leaked S7 tools"
    assert any(name.startswith("s7_") for name in s7)
    assert not any(name.startswith("modbus_") for name in s7), "the s7 profile leaked Modbus tools"
