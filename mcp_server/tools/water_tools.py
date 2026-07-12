"""Water-treatment MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``water`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over injected contact-basin readings. Advisory.
"""

from typing import Any, Optional

from iaiops.core.brain import disinfection
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def disinfection_ct(
    points: list[dict[str, Any]], required_ct: Optional[float] = None
) -> dict:
    """[READ][risk=low] Achieved CT vs required CT per contact basin (SWTR disinfection).

    The water-treatment disinfection-credit calc: CT = free-chlorine residual
    (mg/L) × effective (T10) contact time (min). Each basin's achieved CT is
    compared to the required CT for the target log-inactivation — which the
    utility looks up from its state CT tables (temperature / pH / disinfectant
    specific) and passes in. Returns per-basin CT ratios worst-first and whether
    every basin meets its credit. Pure analysis over readings you pass in;
    read-only, advisory. Does NOT embed the CT tables — supply required_ct.

    Args:
        points: [{location, free_chlorine_mg_l, contact_time_min, baffle_factor?,
            required_ct?}] — contact_time_min is the T10 effective contact time;
            baffle_factor (T10/T, default 1.0) scales a theoretical detention time.
        required_ct: Required CT (mg·min/L) used when a point has no required_ct.

    Returns dict: {points_evaluated, standard, all_meet_credit, failing_count,
        points:[{location, achievedCt, requiredCt, ctRatio, status ('adequate'|
        'insufficient'|'no_target'|'no_data'), detail}], worst}.

    Example: disinfection_ct(points=[{"location":"CCB-1","free_chlorine_mg_l":1.2,
        "contact_time_min":30,"baffle_factor":0.7}], required_ct=6.0).
    """
    return disinfection.disinfection_ct(points, required_ct=required_ct)
