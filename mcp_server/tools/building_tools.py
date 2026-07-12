"""Building HVAC MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``building`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over injected AHU readings. Advisory.
"""

from typing import Any

from iaiops.core.brain import hvac
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def economizer_check(
    units: list[dict[str, Any]],
    free_cool_delta_c: float = 2.0,
    min_damper_pct: float = 15.0,
    high_limit_c: float = 18.0,
) -> dict:
    """[READ][risk=low] Air-handler economizer fault detection (building energy FDD).

    Is each AHU using free cooling when it can, and not fighting itself? Flags
    simultaneous heat/cool (both on = waste), not-economizing (outside air cool
    enough for free cooling but the OA damper is at minimum while mechanical
    cooling runs), and economizing-when-locked-out (OAT above the high limit but
    the damper wide open, dragging hot air in). Worst-first, each fault citing the
    temperatures/states behind it. Pure analysis over readings you pass in (BACnet
    AI/BI points); read-only, advisory.

    Args:
        units: [{ahu, oat_c, rat_c, oa_damper_pct?, mech_cooling?, heating?}] —
            outside-air temp, return-air temp, OA damper %, and cooling/heating states.
        free_cool_delta_c: OAT must be this far below RAT for free cooling (default 2).
        min_damper_pct: OA damper at/below this % is "at minimum" (default 15).
        high_limit_c: Economizer high-limit (lockout) OAT (default 18).

    Returns dict: {units_evaluated, summary, fault_count, faults:[{ahu, status
        ('simultaneous_heat_cool'|'not_economizing'|'economizing_when_locked_out'),
        detail}], worst, note}.

    Example: economizer_check(units=[{"ahu":"AHU-3","oat_c":12,"rat_c":23,
        "oa_damper_pct":10,"mech_cooling":true}]).
    """
    return hvac.economizer_check(
        units, free_cool_delta_c=free_cool_delta_c,
        min_damper_pct=min_damper_pct, high_limit_c=high_limit_c,
    )
