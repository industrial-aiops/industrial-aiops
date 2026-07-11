"""Fleet / multi-site MCP tools (always-on brain) — one view over many edge SITES.

A central collector gathers a small status report per site (via a shared historian, or by querying
each site's HTTP/SSE MCP) and these tools roll them up: fleet health status and fleet-wide incident
causes. Read-only, pure over the PROVIDED reports; no device I/O.
"""

from typing import Any, Optional

from iaiops.core.brain import fleet
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fleet_status(
    sites: list[dict[str, Any]],
    stale_after_s: float = 300.0,
    now: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Roll up per-site status reports into one fleet health view.

    The tier above data_quality_fleet_rollup (per-endpoint within one site): this aggregates across
    many edge SITES for central management. A site is 'offline' if its last_seen is older than
    stale_after_s; fleet_status is the worst site status present. Read-only, pure; no device I/O.

    Args:
        sites: Per-site reports, each
            [{site, location?, profile?, status?, score?, issues?, last_seen?}]; status ∈
            ok|degraded|critical|offline (else derived from score); score 0..1.
        stale_after_s: A site with no report newer than this is 'offline' (default 300).
        now: Optional ISO-8601 'now' for deterministic staleness (default: current UTC).

    Returns dict: {site_count, fleet_status, fleet_score, by_status, worst_sites[], sites[]}.

    Example: fleet_status(sites=[{"site":"sh","score":0.9},{"site":"bj","status":"critical"}]).
    """
    return fleet.fleet_rollup(list(sites or []), stale_after_s=stale_after_s, now=now)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fleet_incidents(sites: list[dict[str, Any]]) -> dict:
    """[READ][risk=low] Roll up active RCA incidents across sites → fleet-wide top causes.

    Aggregates the incidents each site reports into a fleet picture: how many incidents, which sites
    are affected, and the most common root causes across the whole fleet. Read-only; no device I/O.

    Args:
        sites: Per-site reports carrying incidents: [{site, incidents:[{cause|primary_cause,
            confidence?}]}].

    Returns dict: {total_incidents, sites_with_incidents, affected_sites[], top_causes[]}.

    Example: fleet_incidents(sites=[{"site":"plant-sh","incidents":[{"cause":"network"}]}]).
    """
    return fleet.fleet_incident_rollup(list(sites or []))
