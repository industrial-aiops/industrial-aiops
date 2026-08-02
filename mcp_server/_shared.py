"""Shared MCP server primitives: the FastMCP instance, manager helper,
error sanitisation, and the ``@tool_errors`` decorator.

Tool modules under ``mcp_server/tools/`` import ``mcp`` from here and register
their ``@mcp.tool()`` functions onto it. ``mcp_server/server.py`` then imports
those modules and runs the server.

Keep ``Optional[X]`` (never PEP 604 ``X | None``) in any FastMCP-reflected tool
signature — on older mcp/pydantic the union eval'd to ``types.UnionType`` crashes
FastMCP's ``issubclass`` check.
"""

import functools
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import Icon, ToolAnnotations

from iaiops import __version__
from iaiops.core.governance import sanitize
from iaiops.core.runtime.config import load_config
from iaiops.core.runtime.connection import ConnectionManager, OTConnectionError
from mcp_server.hints import hints_for

logger = logging.getLogger(__name__)

_DOCTOR_HINT = "Run 'iaiops doctor' to verify endpoint config and reachability."


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only."""
    logger.error("Tool %s failed", tool, exc_info=True)
    _passthrough = (
        ValueError,
        FileNotFoundError,
        KeyError,
        PermissionError,
        TimeoutError,
        ConnectionError,
        OTConnectionError,
    )
    if isinstance(exc, _passthrough):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


def tool_errors(shape: str = "dict") -> Callable:
    """Wrap a tool body in the canonical try/except → ``_safe_error`` pattern.

    Place this *between* ``@governed_tool`` and the function so the audit
    decorator and FastMCP still see the original signature.
    """

    def decorator(func: Callable) -> Callable:
        name = func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — sanitised below
                msg = _safe_error(e, name)
                if shape == "list":
                    return [{"error": msg, "hint": _DOCTOR_HINT}]
                if shape == "str":
                    return f"Error: {msg} {_DOCTOR_HINT}"
                return {"error": msg, "hint": _DOCTOR_HINT}

        return wrapper

    return decorator


class _GovernedFastMCP(FastMCP):
    """FastMCP that annotates every tool from its ``@governed_tool`` metadata.

    ``@mcp.tool()`` is the OUTERMOST decorator on every tool, so the function it
    receives already carries the governance attributes ``hints_for`` reads. Doing
    the derivation here — once — is what keeps the 170-odd registration sites free
    of hand-written hints that could drift from the risk tier they describe.

    An explicit ``annotations=`` argument still wins, for the rare tool that needs
    to say something the harness cannot infer.

    The signature mirrors ``FastMCP.tool`` keyword for keyword rather than taking
    ``*args, **kwargs``. A widened signature would silently absorb upstream's
    "did you forget to call it?" guard — ``@mcp.tool`` without parentheses would
    stop raising and start registering nothing at all, so the tool would vanish
    from the surface with no error to notice.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # FastMCP takes no `version`, and the low-level server it builds defaults
        # to None — which makes the initialize handshake report the MCP SDK's own
        # version as the SERVER's. A client asking "which iaiops am I talking
        # to?" was told `1.28.1`. Found 2026-08-02 by driving this server from the
        # TypeScript SDK, whose client surfaces serverInfo where the Python one
        # keeps it to itself.
        self._mcp_server.version = __version__

    def tool(
        self,
        name: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        annotations: Optional[ToolAnnotations] = None,
        icons: Optional[list[Icon]] = None,
        meta: Optional[dict[str, Any]] = None,
        structured_output: Optional[bool] = None,
    ) -> Callable:
        if callable(name):
            raise TypeError(
                "The @tool decorator was used incorrectly. "
                "Did you forget to call it? Use @tool() instead of @tool"
            )

        def decorator(fn: Callable) -> Callable:
            return super(_GovernedFastMCP, self).tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations if annotations is not None else hints_for(fn),
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )(fn)

        return decorator


mcp = _GovernedFastMCP(
    "iaiops",
    instructions=(
        "Governed, vendor-neutral, READ-FIRST industrial data tap + intelligent "
        "troubleshooting (preview). Protocols: OPC-UA (incl. Historical Access), "
        "Modbus-TCP, S7comm (Siemens + 仿西门子 国产), Mitsubishi MC (Q/L/iQ-R), "
        "MTConnect (CNC machine tools), MQTT/Sparkplug B (UNS, full protobuf "
        "decode), EtherNet/IP (Rockwell/Allen-Bradley Logix tags), EtherCAT "
        "(pysoem/SOEM fieldbus — CoE SDO, PDO, AL-state; Linux+root+NIC+slaves, "
        "optional extra), PROFINET (pnio-dcp — layer-2 DCP discovery/identify/"
        "asset, READ-ONLY, no RT cyclic; raw-socket extra), and the BUILDING edition "
        "(READ-ONLY): BACnet/IP (BAC0 — Who-Is discovery, object-list, present-value "
        "reads for facility/HVAC). (The ENERGY edition — IEC-104 / DNP3 / IEC-61850 — "
        "now ships separately as iaiops-energy.) Building connectors are preview/待核实, "
        "optional extras. Tool exposure is menu'd per "
        "process via the IAIOPS_MCP selection (no implicit default; IAIOPS_MCP=menu "
        "lists profiles, IAIOPS_MCP_NO_BRAIN=1 strips the cross-protocol brain for "
        "multi-process sites with a dedicated iaiops-mcp-brain server). Call "
        "protocols_supported() for the capability "
        "map. Read tools (most of the surface) are non-destructive. CROSS-PROTOCOL "
        "diagnostics: diagnose_dataflow (localize a 'no-data' break: cannot connect "
        "vs stale value vs flatline sensor), alarm_bad_actors (ISA-18.2 alarm-flood "
        "Pareto/chattering/standing), tag_health (bad-quality/flatline/range/"
        "anomaly offenders), historian_health (gap/flatline over a series), "
        "downtime_root_cause (FLAGSHIP: AI downtime root-cause copilot — correlate "
        "alarms/tags/dataflow/state around an incident window into an evidence-cited, "
        "ADVISORY verdict; read-first, cites only real signals, never executes). "
        "ANALYTICS: oee_compute/oee_multidim/downtime_events (OEE + categorized "
        "stoppages), asset_inventory (active device fingerprint), monitor_changes "
        "(bounded change-of-value). A few WRITE/command tools (s7_write_db, "
        "mc_write_words, mqtt_publish, eip_write_tag, ethercat_write_sdo, "
        "ethercat_set_state) are OT-dangerous: governed at HIGH risk_tier, off by "
        "default (dry-run), capture the BEFORE value/state for undo, and need a "
        "recorded approver (MOC). "
        "未经授权勿对生产控制系统写入. An 'endpoint' selects a target from config; "
        "secrets live in an encrypted store unlocked via IAIOPS_MASTER_PASSWORD; "
        "every tool runs through the iaiops governance harness (audit / budget / "
        "risk-tier). Do NOT use for general IT/network devices, Kubernetes, "
        "hypervisors, or backups — this is OT field-protocol telemetry only. Need "
        "another protocol/action? Open a GitHub issue or PR."
    ),
)

_conn_mgr: Optional[ConnectionManager] = None
_conn_mgr_lock = threading.Lock()


def _manager() -> ConnectionManager:
    """Return the connection manager, lazily initialising it from config.

    Double-checked locking: sync tools run concurrently in FastMCP's threadpool
    under the SSE / streamable-http transports, so an unlocked check-then-set
    could build two managers. Mirrors the governance singletons (see
    ``iaiops.core.governance.budget.get_budget``).
    """
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        with _conn_mgr_lock:
            if _conn_mgr is None:
                config_path_str = os.environ.get("IAIOPS_CONFIG")
                config_path = Path(config_path_str) if config_path_str else None
                _conn_mgr = ConnectionManager(load_config(config_path))
    return _conn_mgr


def _target(name: Optional[str] = None) -> Any:
    """Resolve an OT endpoint target by name (or the default endpoint)."""
    return _manager().target(name)
