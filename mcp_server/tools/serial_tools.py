"""Serial ASCII instrument MCP tools (READ-ONLY) — HLD §17.4.

Loads with ``IAIOPS_MCP=serial`` or ``IAIOPS_MCP=sensor``. Decoded reads go
through ``sensor_read_channel`` (the sensor edition) and collection; this module
adds the one thing needed to WRITE a profile: see the raw lines.
"""

from typing import Optional

from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def serial_sniff(endpoint: Optional[str] = None, seconds: float = 5.0, max_lines: int = 20) -> dict:
    """[READ][risk=low] Listen on a serial instrument and return its raw lines.

    Sends nothing — not even a poll query — and needs no profile: it is how a
    profile's pattern is written. The port is opened exclusively and a port in
    use by another program is refused, never taken (D53). Bounded: at most 30 s
    and 200 lines; lines are shown in latin-1 so every byte is visible.

    Args:
        endpoint: Serial endpoint name from config (default endpoint if omitted).
        seconds: How long to listen (0.1–30).
        max_lines: Stop after this many lines (1–200).

    Returns dict: {endpoint, seconds, lines[], note}.
    """
    from iaiops.connectors.serial import ops

    return ops.sniff(_target(endpoint), seconds=seconds, max_lines=max_lines)
