"""Runtime governance assertion (L-1): every registered MCP tool must carry
the @governed_tool harness, verified at server startup."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_server.server import assert_all_tools_governed, mcp, register_profile


@pytest.mark.unit
def test_registered_tools_are_all_governed(full_tool_registry):
    # full_tool_registry registers the TRUE full surface (brain + all protocols
    # + all EDITION_MODULES tools) — the startup gate must clear all of it, not
    # just a single protocol slice.
    assert full_tool_registry, "expected tools to be registered"
    assert_all_tools_governed()  # must not raise


@pytest.mark.unit
def test_ungoverned_tool_fails_startup(monkeypatch: pytest.MonkeyPatch):
    register_profile("opcua")

    def rogue() -> dict:
        return {}

    # monkeypatch.setitem guarantees the rogue entry is removed from the
    # process-global registry even if the assertion below fails or the test is
    # interrupted (a bare insert would leak it into every later test).
    monkeypatch.setitem(mcp._tool_manager._tools, "rogue_tool", SimpleNamespace(fn=rogue))
    with pytest.raises(RuntimeError, match="rogue_tool"):
        assert_all_tools_governed()


@pytest.mark.unit
def test_uninspectable_registry_fails_closed(monkeypatch):
    monkeypatch.setattr(mcp, "_tool_manager", object(), raising=False)
    with pytest.raises(RuntimeError, match="refusing to start"):
        assert_all_tools_governed()
