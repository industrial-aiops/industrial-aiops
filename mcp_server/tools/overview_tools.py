"""Self-description MCP tool: the protocol/capability map (read-only)."""

from iaiops.core.brain import overview
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors
from mcp_server.noegress import NO_EGRESS_ENV, no_egress_active
from mcp_server.readonly import READ_ONLY_ENV, read_only_active

_READ_ONLY_ON = (
    f"{READ_ONLY_ENV} is ON: every write/command tool has been withheld from "
    "this server's tool list. Do not plan a write — the tools do not exist here. "
    "Report what a write would have done and let a human run it on a "
    "write-enabled server."
)
_READ_ONLY_OFF = (
    f"{READ_ONLY_ENV} is off: write/command tools are exposed. They are HIGH "
    "risk_tier and MOC-gated (dry-run + double confirmation + undo capture); "
    "never call one without explicit human instruction."
)
_NO_EGRESS_ON = (
    f"{NO_EGRESS_ENV} is ON: every tool that ships data off this box (message "
    "bus publish, external historian push, remote model narration) has been "
    "withheld from this server's tool list. Do not plan to forward, publish or "
    "narrate anything — those tools do not exist here. Report findings in your "
    "answer instead. Reads still open sockets to plant devices; this gate is "
    "about data leaving, not about the network."
)
_NO_EGRESS_OFF = (
    f"{NO_EGRESS_ENV} is off: tools that ship data off-box (message bus, "
    "external historian, remote model endpoint) are exposed. They send data the "
    "operator already owns to a destination YOU name — confirm the destination "
    "with a human before calling one."
)


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

    Also reports whether this server runs under the read-only gate and the
    no-egress gate, so a model is TOLD each posture instead of having to infer it
    from tools it cannot see. The two are independent — neither implies the other.

    Returns dict: {tool, posture, implemented_protocols:[...], roadmap_stubs:[...],
        protocols:[{protocol, status, library, transport, auth, read_tools,
        write_tools, params}], diagnostics:[...], analytics:[...], tool_counts,
        safety, read_only_mode, read_only_note, no_egress_mode, no_egress_note}.

    Example: protocols_supported().
    """
    read_only = read_only_active()
    no_egress = no_egress_active()
    return {
        **overview.protocols_supported(),
        "read_only_mode": read_only,
        "read_only_note": _READ_ONLY_ON if read_only else _READ_ONLY_OFF,
        "no_egress_mode": no_egress,
        "no_egress_note": _NO_EGRESS_ON if no_egress else _NO_EGRESS_OFF,
    }
