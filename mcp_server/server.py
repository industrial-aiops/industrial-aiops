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

import logging

from mcp_server._shared import _safe_error, mcp, tool_errors

# Importing the tool modules registers every @mcp.tool() onto the shared
# `mcp` instance. Order does not matter; each module is self-contained.
from mcp_server.tools import (  # noqa: F401 — side effects
    analysis_tools,
    asset_tools,
    diagnostics_tools,
    eip_tools,
    ethercat_tools,
    mc_tools,
    modbus_tools,
    monitor_tools,
    mtconnect_tools,
    oee_tools,
    opcua_tools,
    overview_tools,
    s7_tools,
    sparkplug_tools,
)

__all__ = ["mcp", "main", "_safe_error", "tool_errors"]


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
