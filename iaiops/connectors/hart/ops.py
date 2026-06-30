"""HART-IP operations — read-only process-instrumentation telemetry (hart extra).

Reads universal HART variables from a field device via a HART-IP server/gateway:
device identity, primary variable, and the dynamic variables (PV/SV/TV/QV) with
loop current. Write/config/device-specific commands are NOT exposed (OT-dangerous
on live instrumentation). The command codec is verified; the HART-IP transport is
待核实 (see the connector package docstring).
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.hart import codec
from iaiops.connectors.hart.transport import hart_session
from iaiops.core.brain._shared import num, s
from iaiops.core.runtime.connection import OTConnectionError


def _first_response(raw: bytes) -> Any | None:
    """Parse HART response bytes and return the first parsed message (or None)."""
    messages = codec.parse_responses(raw)
    return messages[0] if messages else None


def _read(target: Any, command: str) -> Any | None:
    """Open a session, send one universal read command, return the parsed message."""
    with hart_session(target) as session:
        pdu = codec.build_command(command)
        raw = session.send_hart_pdu(pdu)
    return _first_response(raw)


def hart_device_identity(target: Any) -> dict:
    """[READ] Read the HART universal device identity (command 0)."""
    msg = _read(target, "unique_identifier")
    base = {"endpoint": s(getattr(target, "name", ""), 64), "host": s(target.host, 48)}
    if msg is None:
        return {**base, "error": "no HART response (device/gateway unreachable)"}
    return {
        **base,
        "command": getattr(msg, "command", None),
        "manufacturer_id": getattr(msg, "manufacturer_id", None),
        "device_type": getattr(msg, "device_type", None),
        "device_id": getattr(msg, "device_id", None),
        "hart_revision": getattr(msg, "universal_revision", None),
    }


def hart_primary_variable(target: Any) -> dict:
    """[READ] Read the primary variable (command 1): value + engineering unit."""
    msg = _read(target, "primary_variable")
    base = {"endpoint": s(getattr(target, "name", ""), 64), "host": s(target.host, 48)}
    if msg is None:
        return {**base, "error": "no HART response (device/gateway unreachable)"}
    pv = getattr(msg, "primary_variable", None)
    return {
        **base,
        "command": getattr(msg, "command", None),
        "primary_variable": num(pv) if num(pv) is not None else s(pv, 48),
        "unit_code": getattr(msg, "primary_variable_units", None),
        "device_status": s(getattr(msg, "device_status", ""), 32),
    }


def hart_dynamic_variables(target: Any) -> dict:
    """[READ] Read dynamic variables + loop current (command 3)."""
    msg = _read(target, "dynamic_variables")
    base = {"endpoint": s(getattr(target, "name", ""), 64), "host": s(target.host, 48)}
    if msg is None:
        return {**base, "error": "no HART response (device/gateway unreachable)"}
    variables = []
    for label in ("primary", "secondary", "tertiary", "quaternary"):
        val = getattr(msg, f"{label}_variable", None)
        if val is None:
            continue
        variables.append({
            "name": label,
            "value": num(val) if num(val) is not None else s(val, 48),
            "unit_code": getattr(msg, f"{label}_variable_units", None),
        })
    loop = getattr(msg, "loop_current", getattr(msg, "current", None))
    return {
        **base,
        "command": getattr(msg, "command", None),
        "loop_current_mA": num(loop) if num(loop) is not None else None,
        "variable_count": len(variables),
        "variables": variables,
    }


__all__ = [
    "hart_device_identity",
    "hart_primary_variable",
    "hart_dynamic_variables",
    "OTConnectionError",
]
