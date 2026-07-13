"""Process-industry MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``process`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over injected loop captures. Advisory.
"""

from typing import Any, Optional

from iaiops.core.brain import control_loop as cl
from iaiops.core.brain import heat_exchanger as hx
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def control_loop_health(
    samples: list[dict[str, Any]],
    offset_band: Optional[float] = None,
    op_min: float = 0.0,
    op_max: float = 100.0,
    sat_pct: float = 90.0,
    osc_index_max: float = 0.3,
) -> dict:
    """[READ][risk=low] Triage a PID control loop from a PV/SP/OP capture.

    Is the loop actually controlling? Over a short capture it flags the three
    classic misbehaviours — oscillation (PV crossing SP repeatedly), sustained
    offset (PV sitting away from SP), and output saturation (OP pinned at 0/100 %).
    Returns the mean offset, the error-crossing oscillation index, the OP
    saturation fractions, and a worst-wins verdict. Not a tuner — it triages which
    loops need a look. Pure analysis over readings you pass in; read-only.

    Args:
        samples: [{pv, sp, op?}] — process value, setpoint, controller output.
        offset_band: Offset (PV units) beyond which mean offset is flagged
            (default 2% of mean |SP|).
        op_min: Output lower bound for saturation (default 0).
        op_max: Output upper bound for saturation (default 100).
        sat_pct: Fraction of samples pinned at a bound that counts as saturated (default 90).
        osc_index_max: Error-crossing rate above which the loop is oscillating (default 0.3).

    Returns dict: {samples, meanOffset, meanAbsOffset, offsetBand, crossings,
        oscillationIndex, opSaturationLowPct, opSaturationHighPct, pvStdev,
        verdict ('ok'|'oscillating'|'offset'|'saturated'|'insufficient_data'),
        detail, note}.

    Example: control_loop_health(samples=[{"pv":72.1,"sp":75,"op":100},
        {"pv":72.0,"sp":75,"op":100}, ...]).
    """
    return cl.control_loop_health(
        samples,
        offset_band=offset_band,
        op_min=op_min,
        op_max=op_max,
        sat_pct=sat_pct,
        osc_index_max=osc_index_max,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def heat_exchanger_fouling(
    readings: list[dict[str, Any]],
    min_effectiveness: float = 0.5,
    decline_pct: float = 10.0,
) -> dict:
    """[READ][risk=low] Detect heat-exchanger fouling from stream-temperature trend.

    Is the exchanger fouling? Computes hot-side temperature effectiveness ε =
    (hot_in − hot_out)/(hot_in − cold_in) per reading, and compares the window's
    first half to its second half. Verdict is 'fouling' when the mean effectiveness
    is below min_effectiveness or it declined more than decline_pct — the signature
    that precedes a forced clean. Pure analysis over readings you pass in (OPC-UA/
    Modbus/HART temperature points); read-only, cited by the effectiveness numbers.

    Args:
        readings: [{hot_in, hot_out, cold_in, cold_out?}] °C, in time order.
        min_effectiveness: Mean effectiveness below which it is fouling (default 0.5).
        decline_pct: First-half→second-half decline % that signals fouling (default 10).

    Returns dict: {readings, currentEffectiveness, meanEffectiveness, declinePct,
        verdict ('ok'|'fouling'|'insufficient_data'), detail, note}.

    Example: heat_exchanger_fouling(readings=[{"hot_in":90,"hot_out":60,"cold_in":30},
        {"hot_in":90,"hot_out":68,"cold_in":30}, ...]).
    """
    return hx.heat_exchanger_fouling(
        readings, min_effectiveness=min_effectiveness, decline_pct=decline_pct
    )
