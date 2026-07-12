"""Fab / quality MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``fab`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over an injected measurement series. Advisory.
"""

from typing import Any, Optional

from iaiops.core.brain import pareto as pareto_brain
from iaiops.core.brain import spc as spc_brain
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def spc_check(
    series: list[Any],
    target: Optional[float] = None,
    sigma: Optional[float] = None,
    usl: Optional[float] = None,
    lsl: Optional[float] = None,
) -> dict:
    """[READ][risk=low] SPC control-chart rule check (Western Electric / Nelson).

    Is a measurement series in statistical control, or is something special-cause
    happening? Centers on the process mean (or a target), estimates sigma (or uses
    a supplied one), and applies the standard rules — a point beyond 3σ, 2-of-3
    beyond 2σ, 4-of-5 beyond 1σ, 8-in-a-row one side, 6-point trend — reporting
    each violation by point index. With spec limits it adds Cp / Cpk. Pure analysis
    over the series you pass in; read-only, advisory (each hit cited by its index).

    Args:
        series: Measurements — scalars or {value}.
        target: Center line; omit to use the series mean.
        sigma: Process sigma; omit to estimate from the series (population stdev).
        usl: Upper spec limit (with lsl → Cp/Cpk).
        lsl: Lower spec limit (with usl → Cp/Cpk).

    Returns dict: {samples, center, sigma, verdict ('in_control'|'out_of_control'|
        'insufficient_data'), violation_count, violations:[{rule (1-5), index,
        detail}], capability?:{cp, cpk, usl, lsl}, note}.

    Example: spc_check(series=[10.1,10.0,9.9,10.2,10.0,9.8,10.1,13.5],
        target=10.0, usl=11.0, lsl=9.0).
    """
    return spc_brain.spc_check(series, target=target, sigma=sigma, usl=usl, lsl=lsl)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def defect_pareto(defects: list[dict[str, Any]], vital_pct: float = 80.0) -> dict:
    """[READ][risk=low] Rank defect categories by count and mark the vital few (Pareto).

    The quality follow-on to an SPC signal: which defect categories drive most of
    the loss? Ranks categories by count, computes each one's share and the running
    cumulative share, and marks the vital few that reach the 80% line — where
    containment and CI effort has the most leverage. Pure analysis over records you
    pass in (an inspection / defect log); read-only, each share cited by its count.

    Args:
        defects: [{category, count?}] — with count the rows aggregate by category
            (summing); without it each row counts as one occurrence.
        vital_pct: Cumulative-share line for the vital few (default 80%).

    Returns dict: {total_defects, category_count, categories:[{category, count,
        pct, cumulativePct, vitalFew}], vital_few:[category], vital_pct, note}.

    Example: defect_pareto(defects=[{"category":"scratch","count":40},
        {"category":"particle","count":25}, {"category":"align","count":5}]).
    """
    return pareto_brain.defect_pareto(defects, vital_pct=vital_pct)
