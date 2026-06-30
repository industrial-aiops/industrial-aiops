"""Per-protocol / per-edition named MCP console entry points.

Each ``iaiops-mcp-<name>`` script is sugar over ``IAIOPS_MCP=<name> iaiops-mcp``:
a thin shim that injects the selection then starts the *same* server. These tests
pin that (a) the shim set is data-driven over the profile menu (no divergent
hardcoded list), (b) the injected selection round-trips through the same
``resolve_selection`` path, and (c) the resulting registered tool set is identical
to what the env var would yield.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from mcp_server import entrypoints
from mcp_server.profiles import NAMED_PROFILES, PROTOCOL_MODULES, resolve_selection

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_entrypoint_set_is_data_driven():
    # Every protocol key and every named profile (except the default 'all', which
    # is already served by the plain `iaiops-mcp`) gets a shim — and nothing else.
    expected = set(PROTOCOL_MODULES) | (set(NAMED_PROFILES) - {"all"})
    assert set(entrypoints.ENTRYPOINT_SELECTIONS) == expected
    for name in expected:
        assert hasattr(entrypoints, f"main_{name}"), f"missing shim main_{name}"


def test_console_scripts_match_shims():
    # The declared `iaiops-mcp-<name>` console scripts must exactly cover the
    # data-driven shim set, each pointing at the matching shim — no drift, no typo.
    scripts = tomllib.loads(_PYPROJECT.read_text())["project"]["scripts"]
    named = {n[len("iaiops-mcp-"):]: t for n, t in scripts.items()
             if n.startswith("iaiops-mcp-")}
    assert set(named) == set(entrypoints.ENTRYPOINT_SELECTIONS)
    for name, target in named.items():
        assert target == f"mcp_server.entrypoints:main_{name}"


def test_shim_injects_selection_and_calls_server_main(monkeypatch):
    # The shim must set IAIOPS_MCP to its selection *before* delegating to the
    # shared server.main (which reads the env at run time) — and must not
    # duplicate server logic.
    for name in entrypoints.ENTRYPOINT_SELECTIONS:
        seen: dict[str, str | None] = {}

        def _fake_main(_name=name) -> None:
            import os

            seen["env"] = os.environ.get("IAIOPS_MCP")

        monkeypatch.setattr(entrypoints.server, "main", _fake_main)
        monkeypatch.delenv("IAIOPS_MCP", raising=False)

        getattr(entrypoints, f"main_{name}")()

        assert seen["env"] == name
        # round-trips through the exact same resolver the env var path uses
        assert resolve_selection(seen["env"]) == resolve_selection(name)


def _tool_count(launch: str) -> int:
    """Count tools a fresh process registers, with mcp.run() stubbed out.

    ``launch`` is a Python snippet that triggers registration (either the env-var
    server path or a named shim). mcp.run is patched to print the count instead of
    blocking on stdio.
    """
    code = (
        "from mcp_server._shared import mcp;"
        "mcp.run = lambda *a, **k: print(len(mcp._tool_manager.list_tools()));"
        + launch
    )
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    return int(out.strip())


@pytest.mark.parametrize("name", ["opcua", "modbus", "fab", "energy", "building"])
def test_shim_tool_set_matches_env_var(name):
    via_env = _tool_count(
        f"import os; os.environ['IAIOPS_MCP'] = {name!r};"
        "from mcp_server.server import main; main()"
    )
    via_shim = _tool_count(
        f"from mcp_server.entrypoints import main_{name} as m; m()"
    )
    assert via_shim == via_env
