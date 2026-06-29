"""MCP tool-set selection ("the menu") — pick which protocol tool groups a
server process exposes.

A site typically runs only 1-2 protocols; exposing all 8 floods the model with
tools it can't use. Selection comes from the ``IAIOPS_MCP`` env var (default
``all``): a comma-separated list of protocol keys and/or named profiles, e.g.::

    IAIOPS_MCP=opcua,modbus      # just these two protocols + the brain
    IAIOPS_MCP=fab               # a named profile
    IAIOPS_MCP=opcua             # effectively a single-protocol MCP

The cross-protocol "brain" (OEE / downtime / diagnostics / asset / analysis /
overview) is ALWAYS exposed — it is protocol-agnostic and is the differentiator.
"""

from __future__ import annotations

# protocol key -> tool module under ``mcp_server.tools``
PROTOCOL_MODULES = {
    "opcua": "opcua_tools",
    "modbus": "modbus_tools",
    "s7": "s7_tools",
    "mc": "mc_tools",
    "eip": "eip_tools",
    "mtconnect": "mtconnect_tools",
    "sparkplug": "sparkplug_tools",
    "ethercat": "ethercat_tools",
}

# Always registered: the cross-protocol intelligence layer.
BRAIN_MODULES = (
    "overview_tools",
    "analysis_tools",
    "diagnostics_tools",
    "asset_tools",
    "oee_tools",
    "monitor_tools",
)

# Named profiles expand to protocol keys. These are MCP *exposure* menus and are
# independent of the pip extras that happen to share some names.
NAMED_PROFILES: dict[str, tuple[str, ...]] = {
    "all": tuple(PROTOCOL_MODULES),
    "fab": ("opcua", "s7", "modbus"),
    "factory": ("modbus", "s7", "eip", "mc", "ethercat", "mtconnect", "opcua", "sparkplug"),
    "process": ("opcua", "modbus"),
}


class UnknownProtocolError(ValueError):
    """Raised when an IAIOPS_MCP token is neither a known protocol nor a profile."""


def resolve_selection(spec: str | None) -> list[str]:
    """Parse an ``IAIOPS_MCP`` spec into an ordered, de-duplicated protocol list.

    ``spec`` is a comma-separated mix of protocol keys and named profiles.
    None / empty → the ``all`` profile. An unknown token raises
    :class:`UnknownProtocolError` listing the valid set, so a typo fails fast
    instead of silently exposing the wrong surface.
    """
    if not spec or not spec.strip():
        spec = "all"
    selected: list[str] = []
    for raw in spec.split(","):
        tok = raw.strip().lower()
        if not tok:
            continue
        if tok in NAMED_PROFILES:
            keys: tuple[str, ...] = NAMED_PROFILES[tok]
        elif tok in PROTOCOL_MODULES:
            keys = (tok,)
        else:
            valid = ", ".join(sorted(set(PROTOCOL_MODULES) | set(NAMED_PROFILES)))
            raise UnknownProtocolError(f"Unknown IAIOPS_MCP token '{tok}'. Valid: {valid}.")
        for k in keys:
            if k not in selected:
                selected.append(k)
    if not selected:
        # A non-empty but content-free spec (e.g. "," or ", ,") is a misconfig —
        # fail fast rather than silently exposing a brain-only, zero-protocol server.
        valid = ", ".join(sorted(set(PROTOCOL_MODULES) | set(NAMED_PROFILES)))
        raise UnknownProtocolError(
            f"IAIOPS_MCP={spec!r} selected no protocols. Use a comma list and/or a "
            f"profile: {valid}."
        )
    return selected


def selected_tool_modules(spec: str | None) -> list[str]:
    """Ordered tool modules to import for ``spec``: brain first, then protocols."""
    return list(BRAIN_MODULES) + [PROTOCOL_MODULES[k] for k in resolve_selection(spec)]
