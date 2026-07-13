"""MCP tool-set selection ("the menu") — pick which protocol tool groups a
server process exposes.

A site typically runs only 1-2 protocols; exposing all 12 floods the model with
tools it can't use. Selection comes from the ``IAIOPS_MCP`` env var — a
comma-separated list of protocol keys and/or named profiles, e.g.::

    IAIOPS_MCP=opcua,modbus      # just these two protocols + the brain
    IAIOPS_MCP=fab               # a named profile
    IAIOPS_MCP=opcua             # effectively a single-protocol MCP
    IAIOPS_MCP=brain             # cross-protocol brain only (dedicated brain server)
    IAIOPS_MCP=menu              # print the selection menu and exit
    IAIOPS_MCP=all               # everything — explicit power-user opt-in only

There is deliberately NO default: a bare ``iaiops-mcp`` prints the menu to
stderr and exits 2 instead of silently exposing 100+ tools.

The cross-protocol "brain" (OEE / downtime / diagnostics / asset / analysis /
overview) is included by default — it is protocol-agnostic and is the
differentiator. Multi-process sites running a dedicated ``iaiops-mcp-brain``
server can strip it from their protocol servers with ``IAIOPS_MCP_NO_BRAIN=1``
to avoid duplicate tool names across servers; the tiny always-on META surface
(``protocols_supported``, the discovery tool) stays exposed regardless.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    "secsgem": "secsgem_tools",
    "profinet": "profinet_tools",
    "bacnet": "bacnet_tools",
    "hart": "hart_tools",
    "fins": "fins_tools",
    "iolink": "iolink_tools",
}

# Always registered, even under IAIOPS_MCP_NO_BRAIN: the self-description /
# discovery surface (``protocols_supported``). Kept tiny on purpose so N
# protocol servers + 1 brain server only ever collide on this one stable tool.
META_MODULES: tuple[str, ...] = ("overview_tools",)

# Registered by default: the cross-protocol intelligence layer.
BRAIN_MODULES = (
    "overview_tools",
    "analysis_tools",
    "diagnostics_tools",
    # ISA-18.2 alarm-flood deepening (episodes / chattering / stale / worksheet).
    "alarm_tools",
    "asset_tools",
    "asset_model_tools",
    "alias_store_tools",
    "oee_tools",
    "monitor_tools",
    # 信创 / compliance self-assessment + national-TSDB historian sink.
    "compliance_tools",
    # Queryability layer (A2): export the local SQLite sink (CSV/SQLite/Parquet).
    "export_tools",
    # Conservative baseline learning (A6): change-log baseline, silent by default.
    "baseline_tools",
    # Historian READ integration (A7): query history back out of the sinks.
    "historian_tools",
    # Adapter belt — stream egress (publish reads/findings to a bus, e.g. NATS) and on-box
    # LLM narration of a cited RCA verdict (air-gapped, Ollama). Read-first; optional extras.
    "egress_tools",
    "llm_tools",
    # Fleet / multi-site rollup — central view over many edge sites (health + incidents).
    "fleet_tools",
    # Predictive maintenance — trend + time-to-threshold forecast (early warning above baseline).
    "pdm_tools",
    # Downtime triage copilot — composes alarm cascade + RCA verdict + PdM precursors
    # into one triage and cross-checks whether the first-out alarm agrees with the cause.
    "downtime_tools",
    # Legacy PLC program explainer (A8): outline/xref/section over EXPORTED
    # ST/AWL/L5X text files — read-only, cite-first, never a live PLC upload.
    "plc_program_tools",
)

# Named profiles expand to protocol keys. These are MCP *exposure* menus and are
# independent of the pip extras that happen to share some names.
NAMED_PROFILES: dict[str, tuple[str, ...]] = {
    "all": tuple(PROTOCOL_MODULES),
    # Brain-only server (B3): zero protocols — just the cross-protocol brain.
    # Pair with IAIOPS_MCP_NO_BRAIN=1 protocol servers at multi-process sites.
    "brain": (),
    "fab": ("secsgem", "opcua", "s7", "modbus"),
    "factory": ("modbus", "s7", "eip", "mc", "fins", "ethercat", "profinet",
                "mtconnect", "opcua", "sparkplug", "iolink"),
    "process": ("opcua", "modbus", "hart"),
    # Building edition: facility / HVAC / 厂务 (BACnet, plus common plant protocols).
    "building": ("bacnet", "modbus", "opcua", "iolink"),
    # Phoenix Contact PLCnext vPLC (虚拟化 PLC): reached over its built-in OPC-UA
    # server (opc.tcp 4840) + Modbus-TCP process-data server — no new connector.
    "plcnext": ("opcua", "modbus"),
    # Water treatment edition (水处理): plants run Modbus RTU/TCP field devices,
    # OPC-UA SCADA gateways and HART-IP process instrumentation — all shipped.
    "water": ("modbus", "opcua", "hart"),
    # Renewables edition (光伏/风电): PV inverters + wind-turbine controllers over Modbus
    # (SUN2000/Growatt templates) + OPC-UA plant SCADA + MQTT-Sparkplug telemetry.
    "renewables": ("modbus", "opcua", "sparkplug"),
    # Warehouse / intralogistics edition (仓储/物料搬运): conveyor & sorter drives over
    # EtherNet/IP (Rockwell) + Profinet (Siemens), VFD/energy meters over Modbus
    # (conveyor_vfd / agv_battery templates), WMS/WCS gateways over OPC-UA, and AMR/IoT
    # telemetry over MQTT-Sparkplug. PdM (pdm_forecast) + downtime + OEE reused as-is.
    "warehouse": ("eip", "profinet", "modbus", "opcua", "sparkplug"),
    # Clinical-facility edition (医疗设施): hospital facilities as a distinct vertical
    # from generic building management. BACnet BMS (isolation-room pressurization +
    # medical-gas safety checks), Modbus (gas alarm panels / energy meters), OPC-UA
    # (plant SCADA). Patient-safety framing over the same building brain.
    "clinical": ("bacnet", "modbus", "opcua"),
}

# Per-edition tool modules — extra ``@mcp.tool`` groups a named EDITION carries
# beyond the protocols it expands to and the always-on brain. They load ONLY when
# that edition is selected (never for a bare protocol key, never in the global
# brain), so edition-specific tools stay OFF single-protocol / other-edition
# surfaces and do not inflate the always-on brain. Keyed by NAMED_PROFILES name.
EDITION_MODULES: dict[str, tuple[str, ...]] = {
    # Facility patient-safety checks (isolation-room pressurization + medical-gas)
    # ride the building & clinical editions — a raw ``bacnet`` selection (a dev
    # poking one device) does not need them. building also gets AHU economizer FDD.
    # BAS controller-layer tools (vendor supervisory REST above BACnet — Metasys
    # OpenBlue / Niagara oBIX) ride the building edition only.
    "building": ("clinical_tools", "building_tools", "bas_tools"),
    "clinical": ("clinical_tools",),
    # Line throughput / bottleneck (Theory-of-Constraints) + sortation performance
    # are material-handling concerns — they ride the warehouse edition.
    "warehouse": ("warehouse_tools",),
    # PID control-loop triage (oscillation / offset / saturation) is a process-
    # industry concern — it rides the process edition.
    "process": ("process_tools",),
    # SPC control-chart rules are a fab / quality concern — they ride the fab edition.
    "fab": ("fab_tools",),
    # Changeover / SMED analysis is a discrete-manufacturing concern — factory edition.
    "factory": ("factory_tools",),
    # Disinfection CT + finished-water quality are water-treatment concerns — water edition.
    "water": ("water_tools",),
    # PV string performance is a solar/renewables concern — renewables edition.
    "renewables": ("renewables_tools",),
}

# ``IAIOPS_MCP=menu`` — not a profile: print the menu and exit(0).
MENU_SELECTION = "menu"

# Env toggle (B3): "1"/"true"/"yes" strips BRAIN_MODULES from protocol servers.
NO_BRAIN_ENV = "IAIOPS_MCP_NO_BRAIN"

# Above this the server logs a tool-flood warning. Raised from 60: the always-on
# brain (~49) plus a full edition's protocols and per-edition EDITION_MODULES now
# lands a legitimate edition in the ~60-85 range (e.g. building ≈ 83), so 60 fired
# on normal editions. 100 sits above any single intended edition yet still flags a
# genuine flood — notably IAIOPS_MCP=all (12 protocols + brain, ~140 tools) — which
# is the "you probably don't want everything" case the warning is meant to catch.
TOOL_FLOOD_WARN_THRESHOLD = 100

_TOOL_DECORATOR_RE = re.compile(r"^@mcp\.tool\(\)", re.MULTILINE)


class UnknownProtocolError(ValueError):
    """Raised when an IAIOPS_MCP token is neither a known protocol nor a profile."""


class NoSelectionError(UnknownProtocolError):
    """Raised when IAIOPS_MCP is unset/empty — there is no implicit default."""


def _valid_tokens() -> str:
    return ", ".join(sorted(set(PROTOCOL_MODULES) | set(NAMED_PROFILES)))


def brain_disabled(env_value: str | None) -> bool:
    """Parse the ``IAIOPS_MCP_NO_BRAIN`` env value ("1"/"true"/"yes" → True)."""
    return (env_value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_selection(spec: str | None) -> list[str]:
    """Parse an ``IAIOPS_MCP`` spec into an ordered, de-duplicated protocol list.

    ``spec`` is a comma-separated mix of protocol keys and named profiles.
    None / empty raises :class:`NoSelectionError` — there is deliberately no
    implicit default (a bare launch must show the menu, not expose 100+ tools).
    An unknown token raises :class:`UnknownProtocolError` listing the valid set,
    so a typo fails fast instead of silently exposing the wrong surface.

    The ``brain`` profile resolves to an empty protocol list on purpose (the
    brain modules are added by :func:`selected_tool_modules`, not here).
    """
    if not spec or not spec.strip():
        raise NoSelectionError(
            "IAIOPS_MCP is not set — there is no default tool selection. "
            f"Set IAIOPS_MCP to one of: {_valid_tokens()} (or a comma list), "
            "use a pre-scoped iaiops-mcp-<name> entrypoint, or IAIOPS_MCP=menu "
            "to print the menu."
        )
    selected: list[str] = []
    saw_valid_token = False
    for raw in spec.split(","):
        tok = raw.strip().lower()
        if not tok:
            continue
        if tok in NAMED_PROFILES:
            keys: tuple[str, ...] = NAMED_PROFILES[tok]
        elif tok in PROTOCOL_MODULES:
            keys = (tok,)
        else:
            raise UnknownProtocolError(
                f"Unknown IAIOPS_MCP token '{tok}'. Valid: {_valid_tokens()}."
            )
        saw_valid_token = True
        for k in keys:
            if k not in selected:
                selected.append(k)
    if not saw_valid_token:
        # A non-empty but content-free spec (e.g. "," or ", ,") is a misconfig —
        # fail fast rather than silently exposing a brain-only, zero-protocol server.
        raise UnknownProtocolError(
            f"IAIOPS_MCP={spec!r} selected nothing. Use a comma list and/or a "
            f"profile: {_valid_tokens()}."
        )
    return selected


def selected_tool_modules(spec: str | None, *, include_brain: bool = True) -> list[str]:
    """Ordered tool modules to import for ``spec``: brain/meta first, then protocols.

    ``include_brain=False`` (the ``IAIOPS_MCP_NO_BRAIN=1`` path) keeps only the
    META discovery surface in front of the protocol modules, for multi-process
    sites that run a dedicated brain server.
    """
    base = list(BRAIN_MODULES) if include_brain else list(META_MODULES)
    extras: list[str] = []
    for edition in selected_editions(spec):
        for module in EDITION_MODULES.get(edition, ()):
            if module not in base and module not in extras:
                extras.append(module)
    protocols = [PROTOCOL_MODULES[k] for k in resolve_selection(spec)]
    return base + extras + protocols


def selected_editions(spec: str | None) -> list[str]:
    """Named editions present in ``spec`` (order-preserving, de-duplicated).

    Each returned edition contributes its :data:`EDITION_MODULES` beyond the
    protocols it expands to. A bare protocol key contributes no edition modules.
    """
    editions: list[str] = []
    for raw in (spec or "").split(","):
        tok = raw.strip().lower()
        if tok in NAMED_PROFILES and tok not in editions:
            editions.append(tok)
    return editions


def _tool_counts_per_module() -> dict[str, int]:
    """Static ``@mcp.tool()`` count per tool module (no imports → no registration)."""
    tools_dir = Path(__file__).resolve().parent / "tools"
    return {
        path.stem: len(_TOOL_DECORATOR_RE.findall(path.read_text("utf-8")))
        for path in sorted(tools_dir.glob("*.py"))
    }


def selection_tool_count(spec: str, *, include_brain: bool = True) -> int:
    """Number of MCP tools a server launched with ``spec`` would expose."""
    counts = _tool_counts_per_module()
    return sum(counts.get(m, 0) for m in selected_tool_modules(spec, include_brain=include_brain))


def menu_text() -> str:
    """Human-readable selection menu (named profiles + protocol keys + tool counts)."""
    counts = _tool_counts_per_module()
    brain_n = sum(counts.get(m, 0) for m in BRAIN_MODULES)
    lines = [
        "iaiops-mcp — tool selection menu (set IAIOPS_MCP, or use a pre-scoped",
        "iaiops-mcp-<name> entrypoint). No default: pick the smallest selection",
        "that covers the site. Each selection below also exposes the",
        f"cross-protocol brain ({brain_n} tools) unless {NO_BRAIN_ENV}=1.",
        "",
        "Named profiles:",
    ]
    for name, keys in NAMED_PROFILES.items():
        n = selection_tool_count(name)
        proto = "+".join(keys) if keys else "(no protocols — brain only)"
        lines.append(f"  IAIOPS_MCP={name:<9} {n:>3} tools  {proto}")
    lines.append("")
    lines.append("Single protocols (combinable, comma-separated):")
    for key in PROTOCOL_MODULES:
        n = selection_tool_count(key)
        lines.append(f"  IAIOPS_MCP={key:<9} {n:>3} tools  ({key} + brain)")
    lines += [
        "",
        "Examples:",
        "  IAIOPS_MCP=opcua,modbus iaiops-mcp        # two protocols + brain",
        "  iaiops-mcp-fab                            # pre-scoped edition entrypoint",
        "  IAIOPS_MCP=brain iaiops-mcp               # dedicated brain-only server",
        f"  {NO_BRAIN_ENV}=1 iaiops-mcp-opcua      # protocol server w/o brain",
        "                                            # (multi-process: 1 brain MCP +",
        "                                            #  N brain-less protocol MCPs;",
        "                                            #  protocols_supported stays on)",
        "  IAIOPS_MCP=all iaiops-mcp                 # everything (tool flood — avoid)",
        "  IAIOPS_MCP=menu iaiops-mcp                # print this menu and exit",
    ]
    return "\n".join(lines)
