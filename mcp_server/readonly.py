"""Read-only registration gate — write tools do not EXIST when it is on.

``IAIOPS_READ_ONLY=1`` makes this server a genuinely read-only tap: every tool
whose governance risk level is ``high`` or ``critical`` (i.e. every tool that can
write a PLC register, a BACnet setpoint or a PROFINET output) is removed from the
FastMCP registry before the server starts serving, so it never appears in
``list_tools()``.

Why removal rather than a call-time refusal: a weak or local model (or a
prompt-injected one) can call any tool it can SEE, and a stray OT write is
physically irreversible. Refusal depends on the harness reaching the check; a
tool absent from the registry cannot be hallucinated into a call at all. The
site operator gets a guarantee, not an instruction.

The gate is a *narrowing* pass: it must run AFTER ``register_profile`` (import is
what registers tools, and registration is additive — it can never narrow an
already-registered surface) and BEFORE ``assert_all_tools_governed``.
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "READ_ONLY_ENV",
    "WRITE_RISK_LEVELS",
    "apply_read_only",
    "read_only_active",
    "read_only_enabled",
]

# Env toggle: "1"/"true"/"yes"/"on" → withhold every write tool.
READ_ONLY_ENV = "IAIOPS_READ_ONLY"

# Governance risk levels that denote a state-changing tool. ``@governed_tool``
# sets ``fn._risk_level``; every MCP tool registered today is either ``low``
# (read/advisory) or one of these. ``medium`` is intentionally absent: no MCP
# tool uses it, and tests/test_read_only_gate.py fails if one appears, so the
# call ("is medium a write?") gets made explicitly rather than by default.
WRITE_RISK_LEVELS: frozenset[str] = frozenset({"high", "critical"})

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def read_only_enabled(env_value: str | None) -> bool:
    """Parse the ``IAIOPS_READ_ONLY`` env value ("1"/"true"/"yes"/"on" → True).

    Same idiom as ``mcp_server.profiles.brain_disabled`` — anything else
    (unset, empty, "0", "false", a typo) is False, so the gate is opt-in and a
    misspelled value never *silently* looks enabled while writes stay exposed.
    """
    return (env_value or "").strip().lower() in _TRUTHY


def read_only_active() -> bool:
    """Whether this process is running under the read-only gate (reads the env)."""
    return read_only_enabled(os.environ.get(READ_ONLY_ENV))


def _risk_level_of(tool: Any) -> str | None:
    """Governance risk level of a registered FastMCP tool, or None if unknown."""
    return getattr(getattr(tool, "fn", None), "_risk_level", None)


def apply_read_only(mcp: Any) -> tuple[str, ...]:
    """Withhold every write tool from ``mcp``'s registry; return the names removed.

    Builds a NEW registry dict containing only the non-write tools and installs
    it — the previous dict is left untouched (no in-place mutation of shared
    state). Tools with no recognisable risk level are KEPT: classifying them is
    ``assert_all_tools_governed``'s job, and dropping them here would silently
    shrink the read surface for a reason the operator never asked for.

    Raises RuntimeError if the registry cannot be introspected — the gate fails
    closed, because "started anyway" would mean serving write tools to a server
    the operator explicitly asked to be read-only.
    """
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if not isinstance(tools, dict):
        raise RuntimeError(
            f"{READ_ONLY_ENV} is set but the FastMCP tool registry cannot be "
            "introspected (mcp._tool_manager._tools not found) — refusing to "
            "start, because the read-only guarantee cannot be enforced."
        )
    withheld = tuple(
        sorted(name for name, tool in tools.items() if _risk_level_of(tool) in WRITE_RISK_LEVELS)
    )
    manager._tools = {name: tool for name, tool in tools.items() if name not in withheld}
    return withheld
