"""A SECOND MCP implementation — the TypeScript SDK, driving the Python server.

`test_mcp_stdio_live.py` and `test_mcp_http_live.py` both use the Python `mcp`
SDK's client against a server built on that same SDK's `FastMCP`. That earns 2a
for our code — the SDK's own client parses what our server emits — but a
misreading *inside* the SDK would satisfy both ends, which is the caveat note ⁹
in `docs/VERIFICATION-RECORD.md` spells out.

This file removes that assumption the only way it can be removed: another
implementation, in another language, written by other people.
`tests/mcp_ts_client/probe.mjs` uses `@modelcontextprotocol/sdk` (TypeScript) to
spawn the real entrypoint over stdio and reports what it saw as JSON.

It found something immediately. FastMCP takes no `version` and the low-level
server it builds defaults to `None`, so the initialize handshake reported the
**MCP SDK's** version as the server's: a client asking "which iaiops am I
talking to?" was told `1.28.1`. The Python client hides `serverInfo`; the
TypeScript one surfaces it.

Needs `node` and one `npm install` in `tests/mcp_ts_client` — skipped cleanly
without them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from iaiops import __version__

pytestmark = [pytest.mark.integration]

_CLIENT_DIR = Path(__file__).parent / "mcp_ts_client"
_PROBE = _CLIENT_DIR / "probe.mjs"
_PROFILE = "modbus"

needs_node_client = pytest.mark.skipif(
    not (shutil.which("node") and (_CLIENT_DIR / "node_modules").is_dir()),
    reason=(
        "the second MCP implementation needs node and its SDK: "
        "cd tests/mcp_ts_client && npm install"
    ),
)


def _probe(tmp_path: Path) -> dict:
    """Run the TypeScript client and return what it saw."""
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["node", str(_PROBE)],  # noqa: S607 — resolved via PATH by design (skipif checks it)
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "IAIOPS_MCP": _PROFILE,
            "IAIOPS_HOME": str(tmp_path),
            # The interpreter running the tests, not whatever `python` resolves
            # to for node — the server must be THIS checkout's.
            "IAIOPS_PYTHON": sys.executable,
        },
    )
    assert result.returncode == 0, f"the TypeScript client failed:\n{result.stderr[-2000:]}"
    # The server logs to stderr; stdout is the probe's single JSON line.
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node_client
def test_a_typescript_client_completes_a_session_with_this_server(tmp_path: Path) -> None:
    """Initialize, list, call — from an implementation nobody here wrote.

    The tool count and the failure-as-content promise are asserted again here
    deliberately: they are the two things the Python-on-both-ends tests could
    have been agreeing with themselves about.
    """
    seen = _probe(tmp_path)

    assert seen["serverInfo"]["name"] == "iaiops", seen
    assert seen["toolCount"] > 10, seen
    assert seen["probedTool"], "the client could not find the tool it was asked for"
    assert seen["probedTool"]["hasDescription"] is True
    assert seen["probedTool"]["inputSchemaType"] == "object", seen

    # A connector failure arrives as readable content, not a protocol error, and
    # the session survives it.
    assert seen["call"]["isError"] is False, seen
    assert "nope" in seen["call"]["text"], seen
    assert seen["toolCountAfter"] == seen["toolCount"], seen


@needs_node_client
def test_the_handshake_reports_this_packages_version(tmp_path: Path) -> None:
    """`serverInfo.version` must be iaiops's, not the SDK's.

    It was the SDK's until 2026-08-02 — FastMCP accepts no `version` and the
    low-level server defaults to `None`, so every client was told the `mcp`
    package's version. An agent host that pins behaviour to a server version, or
    an operator reading a connection log, was being told about the wrong package
    entirely.
    """
    seen = _probe(tmp_path)

    assert seen["serverInfo"]["version"] == __version__, (
        f"the handshake says {seen['serverInfo']['version']!r}, this package is "
        f"{__version__!r} — the SDK's version is leaking into serverInfo again"
    )


@needs_node_client
def test_tool_annotations_survive_a_different_parser(tmp_path: Path) -> None:
    """The annotations promise, read by a client that is not ours.

    0.20.1's whole point is that a client can tell a plant write from a browse
    *programmatically*. Every check of that so far has been the Python SDK
    reading what the Python SDK wrote; this is a TypeScript parser reading the
    same bytes off the wire.
    """
    annotations = _probe(tmp_path)["probedTool"]["annotations"]

    assert annotations, "a read tool arrived with no annotations at all"
    assert annotations["readOnlyHint"] is True, annotations
    assert annotations["destructiveHint"] is False, annotations
    # openWorldHint: this tool reaches a device on a plant network.
    assert annotations["openWorldHint"] is True, annotations
