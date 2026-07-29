"""MCP ``ToolAnnotations`` hints are DERIVED from the governance harness.

``@governed_tool`` already records what a tool does to the world (``_risk_level``,
``_egress``, ``_preview_param``, ``_idempotent``). These tests pin the mapping from
those attributes onto the MCP hints, and assert the whole registered surface carries
them — so a new tool cannot ship unannotated by omission, the same way
``_is_governed_tool`` cannot be omitted.

The hints are DECLARATIVE METADATA for clients (they let a client raise a confirm
prompt on a destructive tool), never an authorisation gate — the MCP spec says hints
must not be relied on for security decisions, and enforcement stays in
``@governed_tool``. See docs/HLD.md decision records D1/D3/D4.

Distinct from ``test_tool_annotations.py``, which polices *Python type* annotations
and the docstring risk tag.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest

from iaiops.core.governance import governed_tool
from mcp_server.hints import hints_for


def _read_tool() -> Any:
    @governed_tool(risk_level="low")
    def t() -> dict:
        return {}

    return t


@pytest.mark.unit
def test_read_tool_is_read_only_and_not_destructive() -> None:
    hints = hints_for(_read_tool())
    assert hints is not None
    assert hints.readOnlyHint is True
    assert hints.destructiveHint is False


@pytest.mark.unit
def test_write_tool_is_destructive_and_not_read_only() -> None:
    @governed_tool(risk_level="high", preview_param="dry_run")
    def t(dry_run: bool = True) -> dict:
        return {}

    hints = hints_for(t)
    assert hints is not None
    assert hints.readOnlyHint is False
    assert hints.destructiveHint is True


@pytest.mark.unit
def test_egress_tool_is_not_read_only() -> None:
    """A low-risk tool that ships plant data off-box still acts on the world."""

    @governed_tool(risk_level="low", egress=True)
    def t() -> dict:
        return {}

    hints = hints_for(t)
    assert hints is not None
    assert hints.readOnlyHint is False
    assert hints.destructiveHint is False


@pytest.mark.unit
def test_medium_risk_is_neither_read_only_nor_destructive() -> None:
    @governed_tool(risk_level="medium")
    def t() -> dict:
        return {}

    hints = hints_for(t)
    assert hints is not None
    assert hints.readOnlyHint is False
    assert hints.destructiveHint is False


@pytest.mark.unit
def test_idempotent_flag_is_carried_through() -> None:
    @governed_tool(risk_level="medium", idempotent=True)
    def t() -> dict:
        return {}

    assert hints_for(t).idempotentHint is True


@pytest.mark.unit
def test_idempotent_is_unset_when_not_declared() -> None:
    """Undeclared means unspecified — never an assertion that repeats differ."""

    @governed_tool(risk_level="high", preview_param="dry_run")
    def t(dry_run: bool = True) -> dict:
        return {}

    assert hints_for(t).idempotentHint is None


@pytest.mark.unit
def test_critical_risk_is_destructive() -> None:
    @governed_tool(risk_level="critical")
    def t() -> dict:
        return {}

    hints = hints_for(t)
    assert hints.destructiveHint is True
    assert hints.readOnlyHint is False


@pytest.mark.unit
def test_bare_decorator_still_raises_rather_than_registering_nothing() -> None:
    """``@mcp.tool`` without parens must keep failing loudly, as upstream does.

    A widened ``*args`` override would absorb the guard: the tool would silently
    vanish from the surface instead of erroring at import time.
    """
    from mcp_server._shared import _GovernedFastMCP

    server = _GovernedFastMCP("probe")

    def fn() -> dict:
        return {}

    with pytest.raises(TypeError, match="forget to call it"):
        server.tool(fn)
    assert not server._tool_manager._tools


@pytest.mark.unit
def test_explicit_annotations_win_over_the_derivation() -> None:
    """The escape hatch documented on the subclass must actually work."""
    from mcp.types import ToolAnnotations

    from mcp_server._shared import _GovernedFastMCP

    server = _GovernedFastMCP("probe")
    override = ToolAnnotations(title="hand-written", readOnlyHint=False)

    @server.tool(annotations=override)
    @governed_tool(risk_level="low")
    def t() -> dict:
        return {}

    registered = server._tool_manager._tools["t"]
    assert registered.annotations == override
    assert registered.annotations.title == "hand-written"


@pytest.mark.unit
def test_every_tool_reaches_the_open_world() -> None:
    """This is an OT tap — its tools talk to plant equipment and external systems."""
    assert hints_for(_read_tool()).openWorldHint is True


@pytest.mark.unit
def test_ungoverned_function_gets_no_hints() -> None:
    """No governance metadata → no derived hints, rather than a wrong guess."""

    def plain() -> dict:
        return {}

    assert hints_for(plain) is None


# ── whole-surface contract ────────────────────────────────────────────────────

WRITE_TAG_RE = re.compile(r"^(\[DEPRECATED → [\w.]+\])?\[WRITE\]")


@pytest.mark.unit
def test_every_registered_tool_is_annotated(full_tool_registry) -> None:
    missing = sorted(name for name, tool in full_tool_registry.items() if tool.annotations is None)
    assert not missing, f"tools registered without MCP annotations: {missing}"


@pytest.mark.unit
def test_hints_agree_with_the_governance_harness(full_tool_registry) -> None:
    """Every hint must be re-derivable from the decorator that governs the tool."""
    mismatched = []
    for name, tool in sorted(full_tool_registry.items()):
        expected = hints_for(tool.fn)
        if expected is None or tool.annotations != expected:
            mismatched.append(name)
    assert not mismatched, f"annotations disagree with @governed_tool: {mismatched}"


@pytest.mark.unit
def test_destructive_hints_are_exactly_the_high_risk_tools(full_tool_registry) -> None:
    """The MOC-gated writes are precisely the tools a client should confirm."""
    destructive = {
        name for name, tool in full_tool_registry.items() if tool.annotations.destructiveHint
    }
    high_risk = {
        name
        for name, tool in full_tool_registry.items()
        if getattr(tool.fn, "_risk_level", "low") in ("high", "critical")
    }
    assert destructive == high_risk
    assert destructive, "expected at least the protocol write tools to be destructive"


@pytest.mark.unit
def test_read_only_hints_do_not_contradict_the_docstring_tag(full_tool_registry) -> None:
    """A tool documented ``[WRITE]`` to the agent must not also claim readOnlyHint."""
    offenders = []
    for name, tool in sorted(full_tool_registry.items()):
        doc = inspect.getdoc(tool.fn) or ""
        first_line = doc.splitlines()[0] if doc else ""
        if WRITE_TAG_RE.match(first_line) and tool.annotations.readOnlyHint:
            offenders.append(name)
    assert not offenders, f"[WRITE] tools claiming readOnlyHint: {offenders}"
