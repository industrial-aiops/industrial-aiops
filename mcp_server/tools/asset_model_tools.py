"""Cross-protocol unified asset/tag/alias model MCP tool (READ-ONLY).

Pure brain tool (risk_level='low'): takes per-protocol tag feeds the caller has
already discovered (OPC-UA ``opcua_discover_tags`` + Modbus ``modbus_apply_template``)
and fuses them into ONE asset/tag model with canonical cross-protocol aliases and
a naming-quality view. No device connection — inputs are plain tag dicts.
"""

from typing import Optional

from iaiops.core.brain import asset_model as am
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def cross_protocol_asset_model(feeds: list, site: Optional[str] = None) -> dict:
    """[READ][risk=low] Fuse per-protocol tag feeds into ONE unified asset model.

    Unifies the two per-protocol tag models (OPC-UA address-space discovery +
    Modbus register templates) into one cross-protocol asset/tag/alias model. Tags
    are re-classified with the SAME semantic classifier the OPC-UA layer uses,
    grouped into assets ACROSS protocols (a ``Line1`` OPC-UA folder + a ``Line1``
    Modbus block become one asset), and each gets a canonical alias
    ``<site>.<asset>.<class_or_name>``. Advisory only — aliases are SUGGESTIONS,
    never a server-side rename (OT-dangerous).

    Args:
        feeds: List of per-protocol feeds, each
            ``{protocol, source, asset?, tags:[...]}``. ``tags`` may be OPC-UA
            discovery descriptors (from opcua_discover_tags), Modbus template tags
            (from modbus_apply_template), or already-normalized tags. A feed-level
            ``asset`` is applied to its tags that don't carry their own.
        site: Site prefix for canonical aliases (default 'site').

    Returns dict: {site, protocols, tag_count, asset_count, assets:[{asset,
        protocols, tag_count, classes, tags:[{protocol, source, name, ref, asset,
        unit, klass, canonical_alias, suggested_alias}]}], naming_quality:
        {alias_collisions, cross_protocol_overlaps, cryptic_names, verdict}}.

    Example: cross_protocol_asset_model(feeds=[
        {"protocol":"opcua","source":"line1","tags":[...]},
        {"protocol":"modbus","source":"meter1","asset":"Line1","tags":[...]}],
        site="plant").
    """
    return am.cross_protocol_asset_model(feeds, site or "site")
