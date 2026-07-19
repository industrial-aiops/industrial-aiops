"""Read-only registration gate: write tools must not EXIST under IAIOPS_READ_ONLY.

Prompt-level "please stay read-only" is not a guarantee — a weak/local model can
still emit a call to a write tool that is present in ``list_tools()``. In OT a
stray write lands on a PLC register / BACnet setpoint / PROFINET output and is
physically irreversible. So the gate *removes* high/critical tools from the
FastMCP registry rather than refusing them at call time: a tool that does not
exist cannot be hallucinated into a call.

The registry is process-global, so every test here restores it.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.readonly import (
    READ_ONLY_ENV,
    READ_RISK_LEVELS,
    WRITE_RISK_LEVELS,
    apply_read_only,
    read_only_enabled,
)
from mcp_server.server import mcp

# Risk levels a REGISTERED MCP tool may carry. ``medium`` now counts as a WRITE
# (see the classification note in mcp_server/readonly.py): a medium tool mints or
# re-delegates authority, which a read-only server must not serve.
_KNOWN_RISK_LEVELS = READ_RISK_LEVELS | WRITE_RISK_LEVELS


@pytest.fixture
def restorable_registry(full_tool_registry: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Full tool surface, with the process-global registry restored afterwards."""
    manager = mcp._tool_manager
    original = dict(manager._tools)
    try:
        yield original
    finally:
        manager._tools = original


def _risk_of(tool: Any) -> str | None:
    return getattr(getattr(tool, "fn", None), "_risk_level", None)


def _write_tool_names(registry: dict[str, Any]) -> set[str]:
    return {name for name, tool in registry.items() if _risk_of(tool) in WRITE_RISK_LEVELS}


@pytest.mark.unit
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " on "])
def test_read_only_enabled_accepts_truthy_values(value: str):
    assert read_only_enabled(value) is True


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "", "  ", "0", "false", "no", "off", "maybe"])
def test_read_only_enabled_rejects_falsy_values(value: str | None):
    assert read_only_enabled(value) is False


@pytest.mark.unit
def test_gate_removes_every_write_tool(restorable_registry):
    """After the gate no high/critical tool remains in the registry at all."""
    assert _write_tool_names(restorable_registry), "expected write tools before the gate"
    apply_read_only(mcp)
    remaining = mcp._tool_manager._tools
    assert _write_tool_names(remaining) == set()


@pytest.mark.unit
def test_gate_returns_the_withheld_names(restorable_registry):
    """The return value is the exact, sorted set of names removed."""
    expected = sorted(_write_tool_names(restorable_registry))
    withheld = apply_read_only(mcp)
    assert list(withheld) == expected
    assert set(withheld).isdisjoint(mcp._tool_manager._tools)


@pytest.mark.unit
def test_gate_keeps_every_read_tool(restorable_registry):
    """Nothing but write tools is withheld — the read surface is untouched."""
    expected_kept = {
        n for n in restorable_registry if n not in _write_tool_names(restorable_registry)
    }
    apply_read_only(mcp)
    assert set(mcp._tool_manager._tools) == expected_kept


@pytest.mark.unit
def test_gate_does_not_mutate_the_original_registry_dict(restorable_registry):
    """Immutability: the gate installs a NEW dict, leaving the old one intact."""
    before = dict(restorable_registry)
    apply_read_only(mcp)
    assert restorable_registry == before
    assert mcp._tool_manager._tools is not restorable_registry


@pytest.mark.unit
def test_ungated_surface_is_unchanged(restorable_registry):
    """Falsy / unset env → nobody calls the gate → the surface keeps its writes."""
    assert read_only_enabled(None) is False
    assert len(mcp._tool_manager._tools) == len(restorable_registry)
    assert _write_tool_names(mcp._tool_manager._tools)


@pytest.mark.unit
def test_discovery_tool_survives_the_gate(restorable_registry):
    """``protocols_supported`` is how a model learns what is left — keep it."""
    apply_read_only(mcp)
    assert "protocols_supported" in mcp._tool_manager._tools


@pytest.mark.unit
def test_uninspectable_registry_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mcp, "_tool_manager", object(), raising=False)
    with pytest.raises(RuntimeError, match="read-only"):
        apply_read_only(mcp)


@pytest.mark.unit
def test_protocols_supported_reports_read_only_off(monkeypatch: pytest.MonkeyPatch):
    from mcp_server.tools.overview_tools import protocols_supported

    monkeypatch.delenv(READ_ONLY_ENV, raising=False)
    assert protocols_supported()["read_only_mode"] is False


@pytest.mark.unit
def test_protocols_supported_reports_read_only_on(monkeypatch: pytest.MonkeyPatch):
    from mcp_server.tools.overview_tools import protocols_supported

    monkeypatch.setenv(READ_ONLY_ENV, "1")
    result = protocols_supported()
    assert result["read_only_mode"] is True
    assert READ_ONLY_ENV in result["read_only_note"]


@pytest.mark.unit
def test_no_write_tool_can_escape_the_gate(restorable_registry):
    """CI gate: the invariant holds generically over the whole registry.

    Not a hardcoded name list — if someone adds a write tool (or a NEW risk
    level that the gate does not classify), this fails instead of shipping a
    write tool onto a read-only server.
    """
    unknown = sorted(
        f"{name}(risk={_risk_of(tool)!r})"
        for name, tool in restorable_registry.items()
        if _risk_of(tool) not in _KNOWN_RISK_LEVELS
    )
    assert not unknown, (
        "tools carry a risk level the read-only gate does not classify: "
        + ", ".join(unknown)
        + f" — extend WRITE_RISK_LEVELS in mcp_server/readonly.py (known: "
        f"{sorted(_KNOWN_RISK_LEVELS)})"
    )
    apply_read_only(mcp)
    survivors = sorted(
        name
        for name, tool in mcp._tool_manager._tools.items()
        if _risk_of(tool) not in _KNOWN_RISK_LEVELS - WRITE_RISK_LEVELS
    )
    assert not survivors, f"write tools survived the read-only gate: {survivors}"


@pytest.mark.unit
def test_gate_withholds_a_tool_it_cannot_classify(restorable_registry):
    """An unclassifiable tool is WITHHELD, not served on the benefit of the doubt.

    This reverses the gate's original behaviour, deliberately. It used to keep
    unknown tools, reasoning that classification was
    ``assert_all_tools_governed``'s job — but that check only asserts the
    ``@governed_tool`` marker is present, not that the risk level is one the gate
    understands. A tool with a typo'd level ("hgih") therefore passed governance
    AND got served by a read-only server.

    Selection is now an allowlist of :data:`READ_RISK_LEVELS`. A read-only site
    noticing a missing read tool is a cheap, visible failure; serving one
    unclassifiable tool as if it were safe is not.
    """
    manager = mcp._tool_manager
    manager._tools = {**restorable_registry, "riskless_tool": SimpleNamespace(fn=lambda: {})}
    withheld = apply_read_only(mcp)
    assert "riskless_tool" in withheld
    assert "riskless_tool" not in manager._tools


@pytest.mark.unit
def test_gate_withholds_a_typo_risk_level(restorable_registry):
    """The concrete case the allowlist exists for."""
    manager = mcp._tool_manager
    typo = SimpleNamespace(fn=lambda: {})
    typo.fn._risk_level = "hgih"  # type: ignore[attr-defined]
    manager._tools = {**restorable_registry, "typo_tool": typo}
    assert "typo_tool" in apply_read_only(mcp)


@pytest.mark.unit
@pytest.mark.parametrize("level", ["medium", "high", "critical"])
def test_every_write_level_is_withheld(restorable_registry, level: str):
    """medium included — see the classification note in mcp_server/readonly.py.

    A medium tool mints or re-delegates authority (the case that forced the
    decision was `iaiops-enterprise`'s `approval_approve`, whose n-th approver
    mints the token authorising an OT write). A read-only server that hands out
    write authorisation is a contradiction, so medium is a write here.
    """
    assert level in WRITE_RISK_LEVELS
    manager = mcp._tool_manager
    tool = SimpleNamespace(fn=lambda: {})
    tool.fn._risk_level = level  # type: ignore[attr-defined]
    manager._tools = {**restorable_registry, f"{level}_tool": tool}
    assert f"{level}_tool" in apply_read_only(mcp)


@pytest.mark.unit
def test_read_and_write_levels_do_not_overlap():
    """The two sets are complements, not overlapping opinions."""
    assert not (READ_RISK_LEVELS & WRITE_RISK_LEVELS)
