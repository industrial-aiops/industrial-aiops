"""Runtime governance assertion (L-1): every registered MCP tool must carry
the @governed_tool harness, verified at server startup."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_server.server import assert_all_tools_governed, mcp, register_profile


@pytest.mark.unit
def test_registered_tools_are_all_governed():
    register_profile("opcua")
    assert mcp._tool_manager._tools, "expected tools to be registered"
    assert_all_tools_governed()  # must not raise


@pytest.mark.unit
def test_ungoverned_tool_fails_startup():
    register_profile("opcua")

    def rogue() -> dict:
        return {}

    tools = mcp._tool_manager._tools
    tools["rogue_tool"] = SimpleNamespace(fn=rogue)
    try:
        with pytest.raises(RuntimeError, match="rogue_tool"):
            assert_all_tools_governed()
    finally:
        del tools["rogue_tool"]


@pytest.mark.unit
def test_uninspectable_registry_fails_closed(monkeypatch):
    monkeypatch.setattr(mcp, "_tool_manager", object(), raising=False)
    with pytest.raises(RuntimeError, match="refusing to start"):
        assert_all_tools_governed()
