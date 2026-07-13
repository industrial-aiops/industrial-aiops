"""HART-IP operations — read-only process-instrumentation telemetry (hart extra).

Reads universal HART variables from a field device via a HART-IP server/gateway:
device identity, primary variable, and the dynamic variables (PV/SV/TV/QV) with
loop current. Write/config/device-specific commands are NOT exposed (OT-dangerous
on live instrumentation). The command codec is verified; the HART-IP transport is
待核实 (see the connector package docstring).

Addressing: a HART device only answers a long frame carrying ITS OWN 5-byte
unique address, so no address is ever fabricated here. Each read resolves the
address as (1) an explicit ``long_address`` (hex, e.g. ``26:06:12:34:56``) given
per call or on the endpoint config, else (2) discovery — a short-frame command-0
identity poll at ``polling address 0`` (the point-to-point default) whose
response yields the unique address used for the actual command. Honest gap: the
discovery poll only reaches a device at polling address 0; multidropped loops or
non-zero polling addresses need ``long_address`` configured. Neither path has
been validated against a live HART-IP gateway (待核实).
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


def _configured_long_address(target: Any, override: str | None) -> bytes | None:
    """Resolve an explicitly-supplied unique address (call arg, else endpoint config)."""
    text = override if override else getattr(target, "long_address", "")
    if not text:
        return None
    return codec.parse_long_address(str(text))


def _session_address(target: Any, session: Any, configured: bytes | None) -> tuple[bytes, Any]:
    """Resolve the device's unique long address for this open session.

    Returns ``(address, identity_message_or_None)`` — the identity message is
    the parsed command-0 response when discovery ran, so an identity read need
    not poll twice. Raises instead of guessing when discovery fails.
    """
    if configured is not None:
        return configured, None
    raw = session.send_hart_pdu(codec.build_identity_poll())
    identity = _first_response(raw)
    if identity is None:
        raise OTConnectionError(
            f"HART identity poll (command 0, polling address 0) on "
            f"'{getattr(target, 'name', '?')}' got no parseable response — cannot "
            f"discover the device's unique long address. If the device is "
            f"multidropped or not at polling address 0, set 'long_address' "
            f"(5 bytes hex, e.g. '26:06:12:34:56') on the endpoint config.",
            endpoint=getattr(target, "host", "?"),
            protocol="hart",
        )
    return codec.unique_address_from_identity(identity), identity


def _read(target: Any, command: str, long_address: str | None = None) -> Any | None:
    """Open a session, send one universal read command, return the parsed message.

    The device address is resolved first (configured, else discovered via the
    command-0 identity poll); the command is then sent to THAT address. An
    identity read reuses the discovery response instead of polling twice.
    """
    configured = _configured_long_address(target, long_address)
    with hart_session(target) as session:
        address, identity = _session_address(target, session, configured)
        if command == "unique_identifier" and identity is not None:
            return identity
        raw = session.send_hart_pdu(codec.build_command(command, address=address))
    return _first_response(raw)


def hart_device_identity(target: Any, long_address: str | None = None) -> dict:
    """[READ] Read the HART universal device identity (command 0)."""
    msg = _read(target, "unique_identifier", long_address)
    base = {"endpoint": s(getattr(target, "name", ""), 64), "host": s(target.host, 48)}
    if msg is None:
        return {**base, "error": "no HART response (device/gateway unreachable)"}
    return {
        **base,
        # Attribute names verified against the hart-protocol cmd-0 parser (2026-06-30).
        "command": getattr(msg, "command", None),
        "manufacturer_id": getattr(msg, "manufacturer_id", None),
        "device_type": getattr(msg, "manufacturer_device_type", None),
        "device_id": getattr(msg, "device_id", None),
        "hart_revision": getattr(msg, "universal_command_revision_level", None),
    }


def hart_primary_variable(target: Any, long_address: str | None = None) -> dict:
    """[READ] Read the primary variable (command 1): value + engineering unit."""
    msg = _read(target, "primary_variable", long_address)
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


def _dynamic_payload(msg: Any) -> dict:
    """Decode a parsed command-3 message into loop current + dynamic variables.

    Shared by :func:`hart_dynamic_variables` (single read) and
    :func:`hart_burst_sample` (repeated reads), so both present identical shapes.
    """
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
    # The hart-protocol cmd-3 parser emits the loop current as 'analog_signal'
    # (verified 2026-06-30); it decodes primary + secondary dynamic variables.
    loop = getattr(msg, "analog_signal", None)
    return {
        "command": getattr(msg, "command", None),
        "loop_current_mA": num(loop) if num(loop) is not None else None,
        "variable_count": len(variables),
        "variables": variables,
    }


def hart_dynamic_variables(target: Any, long_address: str | None = None) -> dict:
    """[READ] Read dynamic variables + loop current (command 3)."""
    msg = _read(target, "dynamic_variables", long_address)
    base = {"endpoint": s(getattr(target, "name", ""), 64), "host": s(target.host, 48)}
    if msg is None:
        return {**base, "error": "no HART response (device/gateway unreachable)"}
    return {**base, **_dynamic_payload(msg)}


# Sampling is bounded so a caller can't ask an MCP tool to hold a session open
# for an unbounded number of round-trips.
_MAX_BURST_SAMPLES = 20


def hart_burst_sample(
    target: Any, samples: int = 3, long_address: str | None = None
) -> dict:
    """[READ] Sample the periodically-published (burst) HART variables.

    In HART *burst mode* the field device publishes its dynamic variables
    periodically without being polled. A true unsolicited HART-IP burst
    subscription is 待核实 (not validated against a live gateway here); this instead
    actively samples the same published variable set — command 3 (dynamic variables
    + loop current) — ``samples`` times over ONE session, so an agent can see the
    published set and spot a stuck/frozen reading. Read-only; no burst-mode config
    is written.
    """
    base = {"endpoint": s(getattr(target, "name", ""), 64), "host": s(target.host, 48)}
    n = max(1, min(int(samples), _MAX_BURST_SAMPLES))
    configured = _configured_long_address(target, long_address)
    collected: list[dict] = []
    with hart_session(target) as session:
        address, _identity = _session_address(target, session, configured)
        pdu = codec.build_command("dynamic_variables", address=address)
        for index in range(n):
            msg = _first_response(session.send_hart_pdu(pdu))
            if msg is None:
                collected.append({"index": index, "error": "no HART response"})
                continue
            collected.append({"index": index, **_dynamic_payload(msg)})
    received = [c for c in collected if "error" not in c]
    return {
        **base,
        "requested_samples": n,
        "received_samples": len(received),
        "samples": collected,
        "note": "Actively sampled the burst/published variables (command 3). A true "
        "unsolicited HART-IP burst subscription is 待核实 — no live-gateway validation.",
    }


__all__ = [
    "hart_device_identity",
    "hart_primary_variable",
    "hart_dynamic_variables",
    "hart_burst_sample",
    "OTConnectionError",
]
