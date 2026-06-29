"""MCP profile/menu selection — IAIOPS_MCP picks which protocol tools are exposed."""

from __future__ import annotations

import subprocess
import sys

import pytest

from mcp_server.profiles import (
    BRAIN_MODULES,
    PROTOCOL_MODULES,
    UnknownProtocolError,
    resolve_selection,
    selected_tool_modules,
)


def test_default_is_all():
    assert resolve_selection(None) == list(PROTOCOL_MODULES)
    assert resolve_selection("") == list(PROTOCOL_MODULES)
    assert resolve_selection("  ") == list(PROTOCOL_MODULES)


def test_comma_list_dedup_and_order():
    assert resolve_selection("opcua,modbus") == ["opcua", "modbus"]
    # de-dupe, preserve first-seen order, case/space-insensitive
    assert resolve_selection(" Modbus , opcua , modbus ") == ["modbus", "opcua"]


def test_named_profile_expands():
    assert resolve_selection("fab") == ["secsgem", "opcua", "s7", "modbus"]
    # a profile combined with an extra protocol, de-duped
    assert resolve_selection("fab,eip") == ["secsgem", "opcua", "s7", "modbus", "eip"]


def test_unknown_token_fails_fast():
    with pytest.raises(UnknownProtocolError) as ei:
        resolve_selection("opcua,bacnet")
    assert "bacnet" in str(ei.value)


def test_content_free_spec_fails_fast():
    # truthy-but-empty specs must not silently yield a zero-protocol server
    for bad in (",", ", ,", " , "):
        with pytest.raises(UnknownProtocolError):
            resolve_selection(bad)


def test_selected_modules_always_include_brain():
    mods = selected_tool_modules("opcua")
    assert set(BRAIN_MODULES).issubset(mods)
    assert "opcua_tools" in mods
    assert "modbus_tools" not in mods


def _registered_tool_count(spec: str) -> int:
    """Count tools a fresh server process registers for ``spec`` (isolated)."""
    code = (
        "from mcp_server.server import register_profile;"
        "from mcp_server._shared import mcp;"
        f"register_profile({spec!r});"
        "print(len(mcp._tool_manager.list_tools()))"
    )
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    return int(out.strip())


def test_profile_narrows_exposed_surface():
    all_n = _registered_tool_count("all")
    opcua_n = _registered_tool_count("opcua")
    fab_n = _registered_tool_count("fab")
    # a single protocol exposes strictly fewer tools than the full set …
    assert opcua_n < all_n
    # … and a 3-protocol profile sits in between
    assert opcua_n < fab_n < all_n
