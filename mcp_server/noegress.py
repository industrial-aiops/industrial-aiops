"""No-egress registration gate — data-shipping tools do not EXIST when it is on.

``IAIOPS_NO_EGRESS=1`` makes this server a closed box: every tool declared
``@governed_tool(..., egress=True)`` — the ones whose job is to transmit local or
plant data to a destination the CALLER names (a message bus, an external
historian, a remote model endpoint) — is removed from the FastMCP registry before
the server starts serving, so it never appears in ``list_tools()``.

What this gate is (and is NOT): it answers exactly one question — "can plant data
leave this box?" — and keys off ``egress``. It is NOT an authorisation gate: it
does not ask "may this server change the plant?" That decision belongs to the
caller (agent judgement / account permissions) and is audited by ``@governed_tool``
(risk_level), not enforced by removing tools from the registry.

Why removal rather than a call-time refusal: a weak or local model (or a
prompt-injected one) can call any tool it can SEE, and a process value that has
been published to a broker cannot be un-sent. Refusal depends on the harness
reaching the check; a tool absent from the registry cannot be hallucinated into a
call at all. (This is the exfiltration axis only — an airgap/sealed-box property,
not read/write authorisation.)

SCOPE BOUNDARY — what this gate does NOT promise:

* It is not a firewall. iaiops is a network tap: it must open sockets to PLCs,
  brokers and historians to read anything at all, and this gate does not stop
  that. It removes the tools whose PURPOSE is to send data outward.
* It does not cover the CLI. ``iaiops audit forward`` streams audit rows to a
  SIEM and is not an MCP tool, so no MCP-registry gate can withhold it — block
  it at the host if the box must be sealed.
* It does not police arguments. A tool is withheld or present as a whole; the
  gate never inspects a destination at call time (that would be exactly the
  call-time refusal this design rejects). This is why a tool with a
  caller-supplied destination host is withheld even when its DEFAULT points at
  localhost.

The gate is a *narrowing* pass: it must run AFTER ``register_profile`` (import is
what registers tools, and registration is additive — it can never narrow an
already-registered surface) and BEFORE ``assert_all_tools_governed``.
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "NO_EGRESS_ENV",
    "apply_no_egress",
    "no_egress_active",
    "no_egress_enabled",
]

# Env toggle: "1"/"true"/"yes"/"on" → withhold every egress tool.
NO_EGRESS_ENV = "IAIOPS_NO_EGRESS"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def no_egress_enabled(env_value: str | None) -> bool:
    """Parse the ``IAIOPS_NO_EGRESS`` env value ("1"/"true"/"yes"/"on" → True).

    Same idiom as ``mcp_server.profiles.brain_disabled`` — anything else
    (unset, empty, "0", "false", a typo) is False, so the gate is opt-in and a
    misspelled value never *silently* looks enabled while egress stays exposed.
    """
    return (env_value or "").strip().lower() in _TRUTHY


def no_egress_active() -> bool:
    """Whether this process is running under the no-egress gate (reads the env)."""
    return no_egress_enabled(os.environ.get(NO_EGRESS_ENV))


def _is_egress(tool: Any) -> bool:
    """Whether a registered FastMCP tool declares ``egress=True``.

    A missing ``_egress`` attribute reads as False by design: ``@governed_tool``
    is shared with the iaiops-energy and iaiops-enterprise repos, and the new
    keyword must preserve today's behaviour for a tool decorated by an older
    copy. ``tests/test_egress_gate.py`` is what stops an egress tool from
    reaching that default by accident.
    """
    return bool(getattr(getattr(tool, "fn", None), "_egress", False))


def apply_no_egress(mcp: Any) -> tuple[str, ...]:
    """Withhold every egress tool from ``mcp``'s registry; return the names removed.

    Builds a NEW registry dict containing only the non-egress tools and installs
    it — the previous dict is left untouched (no in-place mutation of shared
    state).

    Raises RuntimeError if the registry cannot be introspected — the gate fails
    closed, because "started anyway" would mean serving data-shipping tools on a
    server the operator explicitly asked to keep sealed.
    """
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if not isinstance(tools, dict):
        raise RuntimeError(
            f"{NO_EGRESS_ENV} is set but the FastMCP tool registry cannot be "
            "introspected (mcp._tool_manager._tools not found) — refusing to "
            "start, because the no-egress guarantee cannot be enforced."
        )
    withheld = tuple(sorted(name for name, tool in tools.items() if _is_egress(tool)))
    manager._tools = {name: tool for name, tool in tools.items() if name not in withheld}
    return withheld
