"""HART-IP MCP tools — read-only process-instrumentation telemetry (hart extra).

Governed at risk_level='low' (monitor direction). Write/config/device-specific
commands are intentionally NOT exposed (OT-dangerous on live instrumentation).
``hart-protocol`` is an OPTIONAL extra (``pip install iaiops[hart]``) imported
lazily; when missing, every tool returns a teaching error dict. The command codec
is verified; the HART-IP wire transport is 待核实 (no live-gateway validation).
"""

from typing import Optional

from iaiops.connectors.hart import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def hart_device_identity(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] HART universal device identity (command 0) via HART-IP.

    Args:
        endpoint: Endpoint name from config (protocol 'hart'); omit for default.

    Returns dict: {endpoint, host, command, manufacturer_id, device_type,
        device_id, hart_revision}.
    """
    return ops.hart_device_identity(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def hart_primary_variable(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] HART primary variable (command 1): value + unit code.

    Args:
        endpoint: Endpoint name from config (protocol 'hart'); omit for default.

    Returns dict: {endpoint, host, command, primary_variable, unit_code, device_status}.
    """
    return ops.hart_primary_variable(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def hart_dynamic_variables(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] HART dynamic variables + loop current (command 3) via HART-IP.

    Args:
        endpoint: Endpoint name from config (protocol 'hart'); omit for default.

    Returns dict: {endpoint, host, command, loop_current_mA, variable_count,
        variables:[{name, value, unit_code}]}.
    """
    return ops.hart_dynamic_variables(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def hart_burst_sample(endpoint: Optional[str] = None, samples: int = 3) -> dict:
    """[READ][risk=low] Sample the periodically-published (burst) HART variables.

    HART burst mode has the field device publish its dynamic variables periodically.
    A true unsolicited HART-IP burst subscription is 待核实 (no live gateway); this
    actively samples the same published set (command 3 — dynamic variables + loop
    current) ``samples`` times over one session, so an agent can see the published
    variables and spot a stuck/frozen reading. Read-only; no burst config is written.

    Args:
        endpoint: Endpoint name from config (protocol 'hart'); omit for default.
        samples: Number of samples to collect (1..20; default 3).

    Returns dict: {endpoint, host, requested_samples, received_samples,
        samples:[{index, command, loop_current_mA, variable_count,
        variables:[{name, value, unit_code}]}], note}.
    """
    return ops.hart_burst_sample(_target(endpoint), samples=samples)
