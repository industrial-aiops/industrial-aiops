"""Discrete-manufacturing MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``factory`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over injected good-part records. Advisory.
"""

from typing import Any

from iaiops.core.brain import changeover
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def changeover_analysis(good_parts: list[dict[str, Any]]) -> dict:
    """[READ][risk=low] Changeover / SMED durations between products.

    Breaks out what OEE availability only aggregates: each changeover is the gap
    between the last good part of one product and the first good part of the next
    — the setup/adjustment time SMED shrinks. Measures every changeover, ranks the
    longest, and totals the lost time, worst-first, each duration cited by its two
    bounding timestamps. Pure analysis over readings you pass in (a good-part
    completion stream from the MES / PLC counters); read-only, advisory.

    Args:
        good_parts: [{timestamp (ISO-8601), product}] — one per good part, any
            order (sorted by time). A changeover is recorded at each product change.

    Returns dict: {good_parts, ignored, changeover_count, changeovers:[{from, to,
        start, end, durationS}], longest, avgDurationS, totalChangeoverS, note}.

    Example: changeover_analysis(good_parts=[{"timestamp":"2026-07-12T08:00:00Z","product":"A"},
        {"timestamp":"2026-07-12T08:45:00Z","product":"B"}]).
    """
    return changeover.changeover_analysis(good_parts)
