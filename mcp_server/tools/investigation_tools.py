"""The investigation layer, through the MCP front end (HLD §13, §3.1).

**Two front-ends, one engine.** Everything here delegates to
``iaiops.core.investigate`` and ``iaiops.core.knowledge`` — the same functions
``iaiops investigate`` / ``relations`` / ``knowledge`` call. Nothing is
recomputed and nothing is re-worded: a tool that produced a plausible answer of
its own would let the two front-ends drift apart while both looked healthy, and
nothing would mark where they diverged.

That drift is not hypothetical. The whole investigation layer — and `readiness`
before it — shipped **CLI-only** while the architecture claimed both. The claim
sat in the HLD and the README and nothing checked it, which is the same shape as
every gap this repo keeps finding: the capability exists, one of the two ways in
does not.

No tool here touches a device. ``line_relation_declare`` writes — a declaration
about the line, into the site knowledge base — and carries `[READ]` for the same
reason ``baseline_record_change`` does: in this repo that tag is about PLANT
state, and the governance harness derives ``readOnlyHint`` from risk level,
preview mode and egress rather than from local writes.
"""

from typing import Optional

from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def investigation_readiness(site: str = "default") -> dict:
    """[READ][risk=low] How far into an investigation this site could get, and what each gap needs.

    `readiness` answers "which scenarios can this site run"; this answers the
    next question down — if something stopped tomorrow, how many of the eight
    evidence steps could actually be walked, and for each one that could not,
    what is missing.

    Contacts nothing: no device, no network, no historian. It is derived from
    the config and the local store, which is what makes it usable on a site
    nobody has been authorised to probe yet.

    Each gap says whether it is *unmet* (you have not supplied it — the fix names
    the command) or *not yet expressible* (this product offers no way to supply
    it at all). Those two send a person to very different places.
    """
    from iaiops.core.investigate import assess_investigation

    return assess_investigation(site=site).as_dict()


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def investigation_open(
    endpoint: str,
    start: str,
    end: str,
    asset: str = "",
    site: str = "default",
) -> dict:
    """[READ][risk=low] Open an investigation over one past window and walk what can be walked.

    Contacts no device — the window is already past, and its evidence is whatever
    was collected at the time. Each of the eight steps records its own outcome:
    `done` (it ran, here is what it found), `refused` (it could not run HERE —
    no samples, no alarm source; a site fact) or `not_possible` (this product
    cannot do it at all).

    The investigation is persisted, so it can be re-read and advanced later.
    """
    from iaiops.core.investigate.live import advance, open_investigation, save_investigation

    inv = advance(
        open_investigation(endpoint=endpoint, start=start, end=end, asset=asset, site=site)
    )
    save_investigation(inv)
    return inv.as_dict()


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def investigation_show(investigation_id: str) -> dict:
    """[READ][risk=low] Re-read a saved investigation — the state it was left in."""
    from iaiops.core.investigate.live import load_investigation

    return load_investigation(investigation_id).as_dict()


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def investigation_list(site: Optional[str] = None) -> dict:
    """[READ][risk=low] List saved investigations, newest first."""
    from iaiops.core.investigate.live import list_investigations

    found = list_investigations()
    if site:
        found = [i for i in found if i.site == site]
    return {"count": len(found), "investigations": [i.as_dict() for i in found]}


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def line_relation_declare(upstream: str, downstream: str, by: str, site: str = "default") -> dict:
    """[READ][risk=low] Record that one asset feeds another — the second RCA axis.

    `[READ]` follows this repo's convention, where the tag is about PLANT state:
    it touches no device, exactly like `baseline_record_change` and
    `adopt_alias_map`, which are the same shape. It does write — a declaration
    about the line, into the site knowledge base.

    With time alone, an upstream stoppage produces a string of equally-confident
    downstream false causes, because on a line downstream co-occurrence is
    guaranteed whatever the cause. That guarantee is exactly why this is a
    declaration and not something inferred (D25): a person stating the line
    order needs no inference at all.

    ``by`` is required — a person is the evidence, and an edge with no author is
    indistinguishable from a guess a year later. Self-loops and cycles are
    refused here, where somebody can still fix them.
    """
    from iaiops.core.knowledge.relations import declare_relation

    rel = declare_relation(upstream, downstream, by=by, site=site)
    return {
        "upstream": rel.upstream,
        "downstream": rel.downstream,
        "by": rel.by,
        "source": rel.source,
        "site": site,
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def line_relations_list(site: str = "default") -> dict:
    """[READ][risk=low] The declared line order for a site, and what each asset feeds."""
    from iaiops.core.knowledge.relations import line_relations

    found = line_relations(site=site)
    return {
        "site": site,
        "count": len(found),
        "relations": [
            {"upstream": r.upstream, "downstream": r.downstream, "by": r.by, "source": r.source}
            for r in found
        ],
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mechanism_library_check(cause: str, protocol: str = "", site: str = "default") -> dict:
    """[READ][risk=low] What a mounted fault-mechanism library says about one candidate cause.

    Three answers, and the difference between the first two is the whole point:

    * ``nothing_known`` — the library has never heard of this cause. **Not** "no
      objection": a knowledge base that knows nothing about something has not
      cleared it.
    * ``known``, not excluded — mechanisms for it apply here, with what would
      confirm each.
    * ``known``, excluded — every mechanism for it is inapplicable to this
      equipment, so the candidate can be ruled out. That is the strong move a
      ranker cannot make.

    It never confirms. Raising a candidate to `confirmed` comes from outside the
    ranking — a measurement, a reproduction, or a person (D29).
    """
    from iaiops.core.knowledge.mechanisms import check_candidate

    return check_candidate(cause, protocol=protocol, site=site)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mechanism_library_list(site: str = "default") -> dict:
    """[READ][risk=low] The fault mechanisms mounted for a site, and where each came from."""
    from iaiops.core.knowledge.mechanisms import mounted_mechanisms

    found = mounted_mechanisms(site=site)
    return {"site": site, "count": len(found), "mechanisms": [m.as_dict() for m in found]}
