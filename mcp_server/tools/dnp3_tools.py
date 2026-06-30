"""DNP3 MCP tools — read-only outstation telemetry (dnp3 extra).

Governed at risk_level='low' (monitor direction). Control (CROB / analog output)
is intentionally NOT exposed in this preview. pydnp3/opendnp3 is an OPTIONAL extra
(``pip install iaiops[dnp3]``) imported lazily; when missing, every tool returns a
teaching error dict. Preview — binding/API shape unverified against a live outstation.
"""

from typing import Optional

from iaiops.connectors.dnp3 import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def dnp3_link_status(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Bring the DNP3 master online and report link/outstation status.

    Args:
        endpoint: Endpoint name from config (protocol 'dnp3'); omit for default.

    Returns dict: {endpoint, host, port, outstation_address, master_address, online}.

    Example: dnp3_link_status(endpoint="rtu2").
    """
    return ops.dnp3_link_status(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def dnp3_integrity_poll(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Class 0/1/2/3 integrity poll → the outstation's database.

    Returns all static points grouped by measurement type (binary_input,
    analog_input, counter, …).

    Args:
        endpoint: Endpoint name from config (protocol 'dnp3').

    Returns dict: {endpoint, outstation_address, point_count, by_type{},
        points:[{type, group, index, value, quality, timestamp}]}.

    Example: dnp3_integrity_poll(endpoint="rtu2").
    """
    return ops.dnp3_integrity_poll(_target(endpoint))
