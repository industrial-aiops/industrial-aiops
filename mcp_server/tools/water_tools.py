"""Water-treatment MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``water`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over injected contact-basin readings. Advisory.
"""

from typing import Any, Optional

from iaiops.core.brain import disinfection
from iaiops.core.brain import water_quality as wq
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def disinfection_ct(points: list[dict[str, Any]], required_ct: Optional[float] = None) -> dict:
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


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def water_quality_compliance(
    points: list[dict[str, Any]], limits: Optional[dict[str, Any]] = None
) -> dict:
    """[READ][risk=low] Grade finished-water readings against drinking-water limits.

    The continuous-compliance companion to disinfection_ct: grades turbidity
    (filtration/pathogen surrogate), free chlorine residual (too low = under-
    disinfected, too high = taste/DBP) and pH per sample point. Defaults —
    turbidity ≤ 1.0 NTU, free chlorine 0.2–4.0 mg/L, pH 6.5–8.5 — are overridable
    per the utility's permit. Each point takes the worst of its parameters,
    worst-first, citing every number. Pure analysis over readings you pass in
    (Modbus/HART analyzers or OPC-UA SCADA); read-only, advisory.

    Args:
        points: [{location, turbidity_ntu?, free_chlorine_mg_l?, ph?}] — only the
            parameters present are graded.
        limits: Optional partial override {param: {low?, high?}} per the permit.

    Returns dict: {points_evaluated, limits, summary, breach_count,
        breaches:[{location, status, flags:[{parameter, value, unit, detail}]}], worst}.

    Example: water_quality_compliance(points=[{"location":"clearwell","turbidity_ntu":1.4,
        "free_chlorine_mg_l":0.15,"ph":7.2}]).
    """
    return wq.water_quality_compliance(points, limits=limits)
