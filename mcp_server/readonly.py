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
    "READ_RISK_LEVELS",
    "WRITE_RISK_LEVELS",
    "apply_read_only",
    "read_only_active",
    "read_only_enabled",
]

# Env toggle: "1"/"true"/"yes"/"on" → withhold every write tool.
READ_ONLY_ENV = "IAIOPS_READ_ONLY"

# The ONLY risk level a read-only server serves. Everything else is withheld.
#
# This is an ALLOWLIST on purpose. The obvious spelling is a denylist of write
# levels, but then anything the list does not recognise — a new level, a typo
# like "hgih", a tool whose level never got set — is served by default, and the
# failure mode of a read-only gate must never be "serve it anyway".
READ_RISK_LEVELS: frozenset[str] = frozenset({"low"})

# Levels that denote a state change, kept as a name because it reads better at
# the call site and in tests. ``medium`` IS one of them.
#
# That was an open question until a medium tool actually appeared. The iaiops
# base has none, and the original gate excluded medium while a test forced the
# decision the day one showed up. It showed up in `iaiops-enterprise`:
# `approval_approve` (the n-th approver MINTS the token that authorises an OT
# write) and `approval_approvers_set` (rewrites WHO may approve — passing []
# reopens approval to anyone). Both are medium, and both are unambiguously state
# changes.
#
# Reclassifying THEM to high would have been the wrong fix: in this family high
# means "OT-dangerous, MOC-gated, needs a recorded approver", so a high
# `approval_approve` is circular — approving would require an approval. The
# honest classification is medium, so the GATE had to learn that medium is a
# write. A read-only server that still lets a caller mint write authorisation is
# a contradiction: it cannot touch the PLC itself, but it can hand out the
# credential that lets something else do it, and the audit trail will show a
# perfectly legitimate approval.
WRITE_RISK_LEVELS: frozenset[str] = frozenset({"medium", "high", "critical"})

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

    Builds a NEW registry dict containing only the read tools and installs it —
    the previous dict is left untouched (no in-place mutation of shared state).

    Selection is an ALLOWLIST (:data:`READ_RISK_LEVELS`), so a tool whose level
    is unrecognised — a new level, a typo, one never set — is WITHHELD rather
    than served. It is better for a read-only site to notice a missing read tool
    than for one unclassifiable tool to be served as if it were safe; the log
    line names everything withheld, so the diagnosis is one restart away.

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
        sorted(name for name, tool in tools.items() if _risk_level_of(tool) not in READ_RISK_LEVELS)
    )
    manager._tools = {name: tool for name, tool in tools.items() if name not in withheld}
    return withheld
