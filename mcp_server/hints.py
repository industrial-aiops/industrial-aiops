"""Derive MCP ``ToolAnnotations`` from the governance harness.

``@governed_tool`` already declares what a tool does to the world. This module
translates that into the four MCP hints so a client — not just a human reading the
``[READ]``/``[WRITE]`` docstring tag — can tell a browse from a plant write and put
a confirm prompt in front of the latter.

**These are hints, not a gate.** The MCP spec is explicit that annotations must not
be relied on for security decisions, and this repo agrees: authorisation is the
caller's call, the tap's guarantee is un-bypassable audit (docs/HLD.md decision
records D1/D3/D4 — the same reasoning that removed the ``IAIOPS_READ_ONLY``
registration gate in 0.19.0). Enforcement stays entirely in ``@governed_tool``:
risk tier, MOC approver, budget, dry-run default, undo capture.

Deriving rather than hand-writing means the hints cannot drift from the governance
they describe, and a new tool is annotated the moment it is governed.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.types import ToolAnnotations

# Risk tiers whose real (non-preview) call changes plant state. These are the
# MOC-gated writes; ``iaiops.core.governance.policy`` owns the full tier list.
_DESTRUCTIVE_TIERS = ("high", "critical")


def hints_for(fn: Any) -> Optional[ToolAnnotations]:
    """Return the hints implied by ``fn``'s ``@governed_tool`` metadata.

    Returns ``None`` for a function carrying no governance metadata — an honest
    "unknown" beats guessing ``readOnlyHint`` for something we know nothing about.

    ``readOnlyHint`` is deliberately narrow: a tool is read-only only when it is
    low risk AND has no dry-run/preview parameter (having one means it has a real
    write mode) AND does not egress. Egress matters because a tool can ship plant
    data to a caller-named destination without touching any device — low risk, but
    emphatically not read-only.

    ``idempotentHint`` is left UNSET unless ``@governed_tool`` positively declares
    ``idempotent=True``. Asserting ``False`` would be a claim — "calling this twice
    differs from calling it once" — that the harness has no basis for, and it leans
    the wrong way for the protocol writes, where writing the same value twice does
    leave the same state. Unset means "not specified", which is the truth.

    ``openWorldHint`` is asserted, not derived: it is ``True`` for every tool, which
    is the spec default and the conservative direction. Most tools here do reach
    plant equipment or an external system, but a minority are closed-domain
    (``protocols_supported``, ``sparkplug_decode_payload``, the template listers).
    Distinguishing them needs a signal the governance harness does not carry today —
    a ``closed_world`` declaration on ``@governed_tool`` would be the honest fix, and
    it would have to land in every repo sharing that decorator.
    """
    if not getattr(fn, "_is_governed_tool", False):
        return None

    risk_level = getattr(fn, "_risk_level", "low")
    has_write_mode = getattr(fn, "_preview_param", None) is not None
    egresses = bool(getattr(fn, "_egress", False))

    return ToolAnnotations(
        readOnlyHint=risk_level == "low" and not has_write_mode and not egresses,
        destructiveHint=risk_level in _DESTRUCTIVE_TIERS,
        idempotentHint=True if getattr(fn, "_idempotent", False) else None,
        openWorldHint=True,
    )
