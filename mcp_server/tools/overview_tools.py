"""Self-description MCP tool: the protocol/capability map (read-only)."""

from iaiops.core.brain import overview
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def protocols_supported() -> dict:
    """[READ][risk=low] Capability map — protocols, status, tools, connection params.

    Call this to discover what iaiops can do before choosing a protocol/tool.
    Lists implemented protocols (OPC-UA incl. HDA, Modbus, S7comm, Mitsubishi MC,
    MTConnect, MQTT/Sparkplug B full-decode, EtherNet/IP Logix) and the EtherCAT
    roadmap stub, plus cross-protocol analytics (OEE/downtime, asset inventory,
    CoV), each with its read/write tools and the endpoint params it needs.

    Returns dict: {tool, posture, implemented_protocols:[...], roadmap_stubs:[...],
        protocols:[{protocol, status, library, transport, auth, read_tools,
        write_tools, params}], diagnostics:[...], analytics:[...], tool_counts,
        safety}.

    Example: protocols_supported().
    """
    return overview.protocols_supported()
