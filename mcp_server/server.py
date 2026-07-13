"""MCP server for iaiops (stdio default; opt-in HTTP/SSE via IAIOPS_MCP_TRANSPORT).

Thin adapter layer: each ``@mcp.tool()`` function (in ``mcp_server/tools/``)
delegates to the ``iaiops`` ops package and is wrapped with the iaiops
``@governed_tool`` harness (audit / budget / risk-tier).

Standalone, self-governed, vendor-neutral OT data tap + intelligent
troubleshooting (preview) over OPC-UA (incl. HDA), Modbus-TCP, S7comm,
Mitsubishi MC, MTConnect, MQTT/Sparkplug B (full decode), and EtherNet/IP
(Logix), plus OEE/downtime + active asset-inventory analytics and an EtherCAT
roadmap stub. Read-first; the few write/command tools are MOC-gated (high
risk_tier).

Source: https://github.com/industrial-aiops/industrial-aiops
License: MIT
"""

import importlib
import logging
import os
import sys

from mcp_server._shared import _safe_error, mcp, tool_errors
from mcp_server.profiles import (
    MENU_SELECTION,
    NO_BRAIN_ENV,
    TOOL_FLOOD_WARN_THRESHOLD,
    NoSelectionError,
    UnknownProtocolError,
    brain_disabled,
    menu_text,
    resolve_selection,
    selected_tool_modules,
)

__all__ = [
    "mcp",
    "main",
    "register_profile",
    "assert_all_tools_governed",
    "_safe_error",
    "tool_errors",
]

logger = logging.getLogger(__name__)


def register_profile(spec: str | None, *, include_brain: bool = True) -> list[str]:
    """Import the tool modules selected by ``spec``, registering their tools.

    Importing a tool module is what registers its ``@mcp.tool()`` functions onto
    the shared ``mcp`` instance — so importing only the selected modules exposes
    only the selected surface. The cross-protocol brain is included unless
    ``include_brain=False`` (the ``IAIOPS_MCP_NO_BRAIN=1`` path — the META
    discovery tool ``protocols_supported`` stays registered regardless).
    Returns the active protocol keys.

    Note: registration is additive within a process (import is sys.modules-cached
    and decoration runs at import) — call once per server process. It cannot
    *narrow* an already-registered surface.
    """
    for mod in selected_tool_modules(spec, include_brain=include_brain):
        importlib.import_module(f"mcp_server.tools.{mod}")
    return resolve_selection(spec)


def assert_all_tools_governed() -> None:
    """Fail startup if any registered MCP tool lacks the governance harness.

    Every tool function must carry ``_is_governed_tool`` (set by
    ``@governed_tool``) so no tool can ship without audit / policy / budget
    coverage. Raises RuntimeError listing offenders — a hard startup gate.
    """
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if not isinstance(tools, dict):
        raise RuntimeError(
            "Cannot introspect the FastMCP tool registry to verify governance "
            "(mcp._tool_manager._tools not found) — refusing to start ungoverned."
        )
    ungoverned = sorted(
        name
        for name, tool in tools.items()
        if not getattr(getattr(tool, "fn", None), "_is_governed_tool", False)
    )
    if ungoverned:
        raise RuntimeError(
            "Ungoverned MCP tools registered (missing @governed_tool): " + ", ".join(ungoverned)
        )


def _registered_tool_count() -> int:
    """Number of tools currently registered on the shared FastMCP instance."""
    tools = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
    return len(tools) if isinstance(tools, dict) else 0


def main() -> None:
    """Run the MCP server over stdio, exposing the IAIOPS_MCP-selected tools.

    - No ``IAIOPS_MCP`` set → print the selection menu to stderr and exit(2)
      (there is no implicit default; a bare launch must not expose 100+ tools).
    - ``IAIOPS_MCP=menu`` → print the same menu and exit(0).
    - ``IAIOPS_MCP_NO_BRAIN=1`` → register the protocol selection without the
      cross-protocol brain (multi-process sites with a dedicated brain server);
      the ``protocols_supported`` discovery tool stays exposed.
    """
    logging.basicConfig(level=logging.INFO)
    spec = os.environ.get("IAIOPS_MCP")
    if spec is not None and spec.strip().lower() == MENU_SELECTION:
        print(menu_text(), file=sys.stderr)
        raise SystemExit(0)
    include_brain = not brain_disabled(os.environ.get(NO_BRAIN_ENV))
    try:
        protocols = register_profile(spec, include_brain=include_brain)
    except NoSelectionError as exc:
        print(menu_text(), file=sys.stderr)
        print(f"\niaiops-mcp: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except UnknownProtocolError as exc:
        print(
            f"iaiops-mcp: {exc}\nRun with IAIOPS_MCP=menu to print the menu.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    assert_all_tools_governed()
    tool_count = _registered_tool_count()
    if tool_count > TOOL_FLOOD_WARN_THRESHOLD:
        logger.warning(
            "Tool flood: %d tools exposed (> %d). Models degrade with wide menus — "
            "narrow IAIOPS_MCP to the site's protocols (IAIOPS_MCP=menu lists "
            "selections), or split into per-protocol servers plus one "
            "IAIOPS_MCP=brain server with %s=1.",
            tool_count,
            TOOL_FLOOD_WARN_THRESHOLD,
            NO_BRAIN_ENV,
        )
    if not include_brain and not protocols:
        logger.warning(
            "%s=1 combined with a brain-only selection leaves just the discovery "
            "tool — this server exposes almost nothing.",
            NO_BRAIN_ENV,
        )
    logger.info(
        "iaiops MCP up — protocols=[%s]%s, %d tools. Narrow with IAIOPS_MCP "
        "(e.g. IAIOPS_MCP=opcua,modbus or IAIOPS_MCP=fab; IAIOPS_MCP=menu for the menu).",
        ", ".join(protocols) or "none",
        " + cross-protocol brain" if include_brain else " (brain disabled)",
        tool_count,
    )
    from mcp_server.transport import run_server

    run_server(mcp)  # stdio by default; IAIOPS_MCP_TRANSPORT=sse|streamable-http to front it
