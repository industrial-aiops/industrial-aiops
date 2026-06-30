"""Adopted alias-map persistence + cross-run diff MCP tools (low-risk).

Two pure brain tools that close the loop on the cross-protocol asset model: adopt
(persist) the canonical alias map a discovery run proposes, then later diff a
fresh run against that stored baseline (added / removed / renamed / reclassified).
Inputs are plain tag feeds — no device connection. The only side effect is an
owner-only JSON file under the iaiops home (``<home>/aliases/<site>.json``); it is
advisory, never a server-side rename.
"""

from typing import Optional

from iaiops.core.brain import alias_store as als
from iaiops.core.brain import asset_model as am
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def adopt_alias_map(feeds: list, site: Optional[str] = None) -> dict:
    """[READ+PERSIST][risk=low] Adopt + persist the canonical alias map for a site.

    Writes a local owner-only advisory JSON file (NOT an OT-device write — hence
    risk=low); see the persistence note below.

    Runs the cross-protocol asset model over ``feeds``, extracts the adopted map
    ``{canonical_alias: {ref, protocol, asset, name, class}}``, and persists it as
    the site's baseline (owner-only JSON under the iaiops home). Re-running
    overwrites the baseline. Advisory — the map is a SUGGESTION, never a
    server-side rename (OT-dangerous).

    Args:
        feeds: Per-protocol tag feeds ``[{protocol, source, asset?, tags:[...]}]``,
            the SAME shape ``cross_protocol_asset_model`` takes.
        site: Site label (a safe file leaf: alphanumeric/_/-). Default 'site'.

    Returns dict: {site, path, tag_count, adopted:{alias: {...}}}.

    Example: adopt_alias_map(feeds=[{"protocol":"opcua","source":"l1","tags":[...]}],
        site="plant").
    """
    label = site or "site"
    model = am.cross_protocol_asset_model(feeds, label)
    adopted = als.extract_alias_map(model)
    path = als.save_alias_map(label, adopted)
    return {
        "site": model["site"],
        "path": str(path),
        "tag_count": len(adopted),
        "adopted": adopted,
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def diff_alias_map(feeds: list, site: Optional[str] = None) -> dict:
    """[READ][risk=low] Diff a fresh discovery run against the adopted baseline.

    Loads the site's previously adopted alias map, re-runs the cross-protocol
    asset model over ``feeds``, and reports how the address space moved: tags
    added / removed / renamed (same ref, new alias) / reclassified (same ref+alias,
    new semantic class), plus a stable|changed verdict. Adopt a baseline first
    with ``adopt_alias_map``.

    Args:
        feeds: Fresh per-protocol tag feeds (same shape as adopt_alias_map).
        site: Site label whose baseline to diff against. Default 'site'.

    Returns dict: {site, verdict, counts:{added,removed,renamed,reclassified},
        added:[...], removed:[...], renamed:[...], reclassified:[...]}.

    Example: diff_alias_map(feeds=[{"protocol":"opcua","source":"l1","tags":[...]}],
        site="plant").
    """
    label = site or "site"
    previous = als.load_alias_map(label)
    model = am.cross_protocol_asset_model(feeds, label)
    current = als.extract_alias_map(model)
    diff = als.diff_alias_map(previous, current)
    return {"site": model["site"], **diff}
