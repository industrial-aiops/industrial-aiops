"""Warehouse / intralogistics MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``warehouse`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over per-station throughput data (WMS/WCS, MES, or
PLC counters). Advisory.
"""

from typing import Any

from iaiops.core.brain import throughput as tp
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def line_bottleneck(stations: list[dict[str, Any]], near_pct: float = 10.0) -> dict:
    """[READ][risk=low] Find a material-handling / production line's throughput constraint.

    Theory-of-Constraints over per-station data: a line runs no faster than its
    slowest station, so the bottleneck is the station with the lowest throughput
    (longest cycle time). Starvation/blocking corroborate — the constraint is
    rarely starved or blocked, while upstream stations block and downstream
    stations starve. Ranks the line, names the constraint and the line rate it
    sets, flags co-constraints running close behind, and tags each station
    starved / blocked — every call citing the number. Pure analysis over readings
    you pass in (WMS/WCS / MES / PLC counters); read-only and advisory.

    Args:
        stations: [{station, throughput_per_hr | cycle_time_s, starved_pct?,
            blocked_pct?}] — give a throughput OR a cycle time (throughput wins;
            cycle time converts as 3600/cycle_time_s).
        near_pct: A station within this % of the slowest is a co-constraint (default 10).

    Returns dict: {stations_analyzed, ignored, bottleneck:{station,
        throughputPerHr, cycleTimeS, starvedPct, blockedPct}, lineRatePerHr,
        ranked:[{station, throughputPerHr, cycleTimeS, starvedPct, blockedPct,
        vsBottleneckPct, flag}], nearBottleneck:[station], note}.

    Example: line_bottleneck(stations=[{"station":"infeed","throughput_per_hr":1200},
        {"station":"sorter","throughput_per_hr":900,"blocked_pct":5},
        {"station":"palletizer","cycle_time_s":4.5,"starved_pct":35}]).
    """
    return tp.line_bottleneck(stations, near_pct=near_pct)
