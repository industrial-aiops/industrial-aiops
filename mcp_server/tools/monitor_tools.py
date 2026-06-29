"""Change-of-value (CoV) monitor MCP tool (READ-ONLY, bounded).

Non-destructive (risk_level='low'). Bounded by both a wall-clock duration and a
max change count — never an open loop.
"""

from typing import Optional

from iaiops.core.brain import monitor as ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def monitor_changes(
    ref: str,
    endpoint: Optional[str] = None,
    duration_s: int = 10,
    interval_ms: int = 500,
    deadband: float = 0.0,
    max_changes: int = 100,
) -> dict:
    """[READ][risk=low] Capture only the value CHANGES of a point over a bounded window.

    Polls ``ref`` and returns only the changes (with timestamps), not every
    sample — the OT deadband-report pattern. Works across OPC-UA / Modbus / S7 /
    Mitsubishi MC / EtherNet/IP. Hard-capped by duration_s and max_changes (never
    an infinite loop).

    Args:
        ref: Point to watch — OPC-UA node id, Modbus address, S7 address string,
            MELSEC device, or Logix tag (per the endpoint's protocol).
        endpoint: Endpoint name from config.
        duration_s: Wall-clock window in seconds (1..120, capped server-side).
        interval_ms: Poll interval in milliseconds (>=50).
        deadband: Numeric change must exceed this to count (0 = any change).
        max_changes: Stop after this many changes (1..500, capped server-side).

    Returns dict: {endpoint, ref, duration_s, interval_ms, deadband, samples_polled,
        change_count, changes:[{value, previous, source_timestamp, wall_clock}]}.

    Example: monitor_changes(ref="ns=2;i=5", endpoint="line1", duration_s=20, deadband=0.5).
    """
    return ops.monitor_changes(
        _target(endpoint), ref, duration_s, interval_ms, deadband, max_changes
    )
