"""MCP profile/menu selection — IAIOPS_MCP picks which protocol tools are exposed.

Also pins the 0.10.0 B2/B3 behavior: no implicit default (bare launch → menu +
exit 2), ``menu`` prints the menu, ``brain`` is a brain-only selection, and
``IAIOPS_MCP_NO_BRAIN=1`` strips the brain (keeping ``protocols_supported``).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from mcp_server.profiles import (
    BRAIN_MODULES,
    META_MODULES,
    NO_BRAIN_ENV,
    PROTOCOL_MODULES,
    TOOL_FLOOD_WARN_THRESHOLD,
    NoSelectionError,
    UnknownProtocolError,
    brain_disabled,
    menu_text,
    resolve_selection,
    selected_tool_modules,
    selection_tool_count,
)


def test_no_default_selection():
    # B2: unset/blank IAIOPS_MCP must NOT silently mean 'all' — it fails fast.
    for empty in (None, "", "  "):
        with pytest.raises(NoSelectionError):
            resolve_selection(empty)


def test_explicit_all_still_works():
    assert resolve_selection("all") == list(PROTOCOL_MODULES)


def test_comma_list_dedup_and_order():
    assert resolve_selection("opcua,modbus") == ["opcua", "modbus"]
    # de-dupe, preserve first-seen order, case/space-insensitive
    assert resolve_selection(" Modbus , opcua , modbus ") == ["modbus", "opcua"]


def test_named_profile_expands():
    assert resolve_selection("fab") == ["secsgem", "opcua", "s7", "modbus"]
    # a profile combined with an extra protocol, de-duped
    assert resolve_selection("fab,eip") == ["secsgem", "opcua", "s7", "modbus", "eip"]


def test_building_profile_resolves():
    assert resolve_selection("building") == ["bacnet", "modbus", "opcua", "iolink"]


def test_unknown_token_fails_fast():
    with pytest.raises(UnknownProtocolError) as ei:
        resolve_selection("opcua,nonexistent-proto")
    assert "nonexistent-proto" in str(ei.value)


def test_content_free_spec_fails_fast():
    # truthy-but-empty specs must not silently yield a zero-protocol server
    for bad in (",", ", ,", " , "):
        with pytest.raises(UnknownProtocolError):
            resolve_selection(bad)


def test_selected_modules_include_brain_by_default():
    mods = selected_tool_modules("opcua")
    assert set(BRAIN_MODULES).issubset(mods)
    assert "opcua_tools" in mods
    assert "modbus_tools" not in mods


# ── B3: brain-only selection + brain opt-out ────────────────────────────────────


def test_brain_selection_resolves_to_zero_protocols():
    assert resolve_selection("brain") == []


def test_brain_selection_modules_are_exactly_brain():
    assert selected_tool_modules("brain") == list(BRAIN_MODULES)


def test_no_brain_keeps_meta_discovery_module():
    # NO_BRAIN protocol server: protocol tools + the tiny META discovery surface
    # (protocols_supported) — nothing else from the brain.
    mods = selected_tool_modules("opcua", include_brain=False)
    assert mods == list(META_MODULES) + ["opcua_tools"]
    assert "diagnostics_tools" not in mods


def test_meta_module_is_within_brain():
    # META must stay a subset of BRAIN so 'brain' + NO_BRAIN servers only ever
    # collide on the stable discovery tool.
    assert set(META_MODULES).issubset(BRAIN_MODULES)


def test_brain_disabled_env_parsing():
    for on in ("1", "true", "TRUE", "yes", "on", " 1 "):
        assert brain_disabled(on)
    for off in (None, "", "0", "false", "no", "banana"):
        assert not brain_disabled(off)


# ── menu ────────────────────────────────────────────────────────────────────────


def test_menu_text_lists_profiles_protocols_counts_examples():
    text = menu_text()
    for name in ("all", "brain", "fab", "factory", "process", "building", "water"):
        assert f"IAIOPS_MCP={name}" in text
    for key in PROTOCOL_MODULES:
        assert f"IAIOPS_MCP={key}" in text
    assert "tools" in text  # per-selection tool counts rendered
    assert NO_BRAIN_ENV in text  # documents the multi-process pattern
    assert "iaiops-mcp-fab" in text  # one-line examples
    assert str(selection_tool_count("all")) in text


def test_selection_tool_counts_are_consistent():
    all_n = selection_tool_count("all")
    opcua_n = selection_tool_count("opcua")
    brain_n = selection_tool_count("brain")
    no_brain_opcua_n = selection_tool_count("opcua", include_brain=False)
    assert brain_n < opcua_n < all_n
    assert no_brain_opcua_n < opcua_n
    # 'all' really is a flood — the startup warning threshold must fire for it.
    assert all_n > TOOL_FLOOD_WARN_THRESHOLD


# ── fresh-process registration behavior ─────────────────────────────────────────


def _run_server(env_overrides: dict[str, str], code: str) -> subprocess.CompletedProcess:
    """Run ``code`` in a fresh interpreter with a controlled IAIOPS_MCP* env."""
    import os

    env = {k: v for k, v in os.environ.items() if k not in ("IAIOPS_MCP", NO_BRAIN_ENV)}
    env.update(env_overrides)
    return subprocess.run(  # noqa: S603 — test fixture, fixed argv
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


_MAIN_STUBBED = (
    "from mcp_server._shared import mcp;"
    "mcp.run = lambda *a, **k: print(len(mcp._tool_manager.list_tools()));"
    "from mcp_server.server import main; main()"
)


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


def test_bare_launch_prints_menu_and_exits_2():
    proc = _run_server({}, _MAIN_STUBBED)
    assert proc.returncode == 2
    assert "IAIOPS_MCP=fab" in proc.stderr  # the menu went to stderr
    assert "no default" in proc.stderr
    assert proc.stdout.strip() == ""  # mcp.run never reached — nothing exposed


def test_menu_selection_prints_menu_and_exits_0():
    proc = _run_server({"IAIOPS_MCP": "menu"}, _MAIN_STUBBED)
    assert proc.returncode == 0
    assert "IAIOPS_MCP=fab" in proc.stderr
    assert proc.stdout.strip() == ""  # menu mode never starts the server


def test_unknown_token_exits_2_with_hint():
    proc = _run_server({"IAIOPS_MCP": "opcua,typo-proto"}, _MAIN_STUBBED)
    assert proc.returncode == 2
    assert "typo-proto" in proc.stderr
    assert "IAIOPS_MCP=menu" in proc.stderr


def test_explicit_all_still_serves_with_flood_warning():
    proc = _run_server({"IAIOPS_MCP": "all"}, _MAIN_STUBBED)
    assert proc.returncode == 0
    n = int(proc.stdout.strip())
    assert n > TOOL_FLOOD_WARN_THRESHOLD
    assert "Tool flood" in proc.stderr  # >60-tool warning logged


def test_small_selection_has_no_flood_warning():
    proc = _run_server({"IAIOPS_MCP": "opcua"}, _MAIN_STUBBED)
    assert proc.returncode == 0
    assert "Tool flood" not in proc.stderr


def test_brain_selection_registers_exactly_brain_tools():
    proc = _run_server({"IAIOPS_MCP": "brain"}, _MAIN_STUBBED)
    assert proc.returncode == 0
    assert int(proc.stdout.strip()) == selection_tool_count("brain")


def test_no_brain_registers_protocol_tools_plus_discovery_only():
    code = (
        "from mcp_server._shared import mcp;"
        "mcp.run = lambda *a, **k: print("
        "','.join(sorted(t.name for t in mcp._tool_manager.list_tools())));"
        "from mcp_server.server import main; main()"
    )
    proc = _run_server({"IAIOPS_MCP": "opcua", NO_BRAIN_ENV: "1"}, code)
    assert proc.returncode == 0
    names = set(proc.stdout.strip().split(","))
    # discovery tool always on, even without the brain
    assert "protocols_supported" in names
    # brain tools gone
    assert "diagnose_dataflow" not in names
    assert "oee_compute" not in names
    # protocol tools present
    assert "opcua_browse" in names
    with_brain = _run_server({"IAIOPS_MCP": "opcua"}, code)
    assert names < set(with_brain.stdout.strip().split(","))
