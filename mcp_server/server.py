"""MCP server wrapping iaiops operations (stdio transport).

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

from mcp_server._shared import _safe_error, mcp, tool_errors
from mcp_server.profiles import resolve_selection, selected_tool_modules

__all__ = ["mcp", "main", "register_profile", "_safe_error", "tool_errors"]

logger = logging.getLogger(__name__)


def register_profile(spec: str | None) -> list[str]:
    """Import the tool modules selected by ``spec``, registering their tools.

    Importing a tool module is what registers its ``@mcp.tool()`` functions onto
    the shared ``mcp`` instance — so importing only the selected modules exposes
    only the selected surface. The cross-protocol brain is always included.
    Returns the active protocol keys.

    Note: registration is additive within a process (import is sys.modules-cached
    and decoration runs at import) — call once per server process. It cannot
    *narrow* an already-registered surface.
    """
    for mod in selected_tool_modules(spec):
        importlib.import_module(f"mcp_server.tools.{mod}")
    return resolve_selection(spec)


def main() -> None:
    """Run the MCP server over stdio, exposing the IAIOPS_MCP-selected protocols."""
    logging.basicConfig(level=logging.INFO)
    protocols = register_profile(os.environ.get("IAIOPS_MCP"))
    logger.info(
        "iaiops MCP up — protocols=[%s] + cross-protocol brain. Narrow with "
        "IAIOPS_MCP (e.g. IAIOPS_MCP=opcua,modbus or IAIOPS_MCP=fab).",
        ", ".join(protocols) or "none",
    )
    mcp.run(transport="stdio")
