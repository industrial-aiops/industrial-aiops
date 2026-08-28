"""Self-description MCP tool: the protocol/capability map (read-only)."""

from iaiops.core.brain import overview
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors
from mcp_server.noegress import NO_EGRESS_ENV, no_egress_active

_WRITE_NOTE = (
    "Write/command tools are exposed and governed, not withheld: they are HIGH "
    "risk_tier and MOC-gated (dry-run + double confirmation + undo capture) and "
    "every call leaves an audit row. Whether a write is authorised is the "
    "caller's decision (agent judgement / account permissions), not this tap's — "
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

    Also reports whether this server runs under the no-egress gate, so a model is
    TOLD the posture instead of having to infer it from tools it cannot see.
    Read/write authorisation is NOT a server posture here — it is the caller's
    decision; every call (read or write, MCP or CLI) is audited.

    Returns dict: {tool, posture, implemented_protocols:[...], roadmap_stubs:[...],
        protocols:[{protocol, status, library, transport, auth, read_tools,
        write_tools, params}], diagnostics:[...], analytics:[...], tool_counts,
        safety, write_note, no_egress_mode, no_egress_note}.

    Example: protocols_supported().
    """
    no_egress = no_egress_active()
    return {
        **overview.protocols_supported(),
        "write_note": _WRITE_NOTE,
        "no_egress_mode": no_egress,
        "no_egress_note": _NO_EGRESS_ON if no_egress else _NO_EGRESS_OFF,
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def site_readiness(db: str = "") -> dict:
    """[READ][risk=low] Which scenarios THIS site can run today, and what each gap needs.

    The companion to `protocols_supported`, one altitude down. That one says what
    the product can do; this says what this installation can do — and calling the
    first without the second is how an agent plans a scenario the site has no
    inputs for.

    Contacts nothing: no device, no network, no historian. It is derived from
    `config.yaml` and the local store, which is what makes it runnable against a
    site nobody has authorised you to probe — the site that most needs it.

    Three states, and the middle one carries the value: `ready`, `degraded` (it
    RUNS, on less than full evidence — root cause without a historian still ranks
    causes, it just cannot see the two hours before the stoppage) and `blocked`.

    `blocked_on` is the actionable half: one missing input usually unlocks several
    scenarios, ranked by how many.

    It never fills a gap in for you. Which tag is the production counter is
    process knowledge, and a wrong guess yields plausible-looking OEE numbers —
    considerably worse than an error (D16). Where a prerequisite cannot be
    supplied at all yet, the row says `not_yet_expressible` rather than implying
    somebody forgot to configure it.

    `db` overrides the local store path; empty means the iaiops store.
    """
    from pathlib import Path

    from iaiops.core.readiness import assess

    return assess(db_path=Path(db).expanduser() if db else None).as_dict()
