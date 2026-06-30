"""OPC-UA tag auto-discovery + semantic modeling (read-only).

The integrator's biggest hidden cost is turning a raw OPC-UA address space into a
usable tag/asset model: thousands of nodes with cryptic browse names, no units,
no grouping. This module walks the address space, collects the **Variable** nodes
(the actual tags), enriches each with datatype / value / engineering unit, infers
a semantic class from its browse name, groups tags into assets by their browse
path, and proposes a clean canonical alias per tag.

It is **advisory and read-only**: nothing is written back to the server — the
alias layer is a suggestion map the operator can adopt, not a server-side rename
(which would be OT-dangerous). The semantic classifier is heuristic and labels
anything it is unsure about ``other`` rather than guessing.

The browse machinery mirrors :mod:`iaiops.connectors.opcua.ops` (same node /
depth caps) so a discovery sweep can never run unbounded.
"""

from __future__ import annotations

from typing import Any

from iaiops.connectors.opcua.ops import _coerce_value, opcua_session
from iaiops.core.brain._shared import s

# Tag semantics (class inference + alias scheme) live in the shared brain home so
# both this connector and the cross-protocol asset model use the SAME rules.
# Re-exported here to keep this module's long-standing public API stable.
from iaiops.core.brain.semantics import classify_tag, suggest_alias

MAX_TAGS = 2000
MAX_DISCOVERY_DEPTH = 8
OBJECTS_NODE = "i=85"


def _read_engineering_unit(node: Any) -> str:
    """Best-effort read of a Variable's EngineeringUnits property (UA EUInformation)."""
    try:
        children = node.get_children()
    except Exception:  # noqa: BLE001 — node may not be browsable
        return ""
    for child in children:
        try:
            if child.read_browse_name().Name != "EngineeringUnits":
                continue
            eu = child.read_value()
        except Exception:  # noqa: BLE001 — property absent / unreadable
            continue
        disp = getattr(eu, "DisplayName", None)
        text = getattr(disp, "Text", None) if disp is not None else None
        return s(text or getattr(eu, "Description", "") or "", 32)
    return ""


def _tag_descriptor(node: Any, path: tuple[str, ...], browse_name: str) -> dict:
    """Build the enriched descriptor for one Variable node (never raises)."""
    asset_path = "/".join(path)
    datatype, value, writable = "", None, False
    try:
        dv = node.read_data_value()
        variant = dv.Value
        datatype = s(getattr(variant.VariantType, "name", ""), 32)
        value = _coerce_value(variant.Value)
    except Exception:  # noqa: BLE001 — value/datatype is best-effort
        pass
    try:
        # get_access_level() returns a set of ua.AccessLevel IntEnum members;
        # str(member) is its integer value ("1"), so match on the .name instead
        # (CurrentWrite) — otherwise every tag reads as read-only.
        access = node.get_access_level()
        writable = any("Write" in getattr(a, "name", "") for a in access)
    except Exception:  # noqa: BLE001 — access level is best-effort
        writable = False
    return {
        "node_id": s(node.nodeid.to_string(), 128),
        "browse_name": s(browse_name, 128),
        "browse_path": s("/".join([*path, browse_name]), 256),
        "asset": s(asset_path, 200),
        "datatype": datatype,
        "value": value,
        "unit": _read_engineering_unit(node),
        "writable": writable,
        "class": classify_tag(browse_name),
        "suggested_alias": suggest_alias(asset_path, browse_name),
    }


def _is_standard(node: Any) -> bool:
    """True for a node in OPC-UA namespace 0 (built-in server infrastructure).

    Process tags always live in a vendor namespace (ns≥1); the ns=0 ``Server``
    object and its diagnostics subtree are infrastructure, not tags — skipping
    them by default keeps a discovery sweep to the real address space.
    """
    try:
        return int(node.nodeid.NamespaceIndex) == 0
    except Exception:  # noqa: BLE001 — if unsure, don't skip
        return False


def _walk_tags(node: Any, path: tuple[str, ...], depth: int, max_depth: int,
               out: list[dict], include_standard: bool, visited: set[str]) -> None:
    """Depth-first walk collecting Variable nodes (bounded by tag/depth caps).

    ``visited`` tracks node ids already emitted/descended so reference cycles and
    shared/aliased nodes (legal in an OPC-UA address space) don't yield duplicate
    rows or re-descend a subtree.
    """
    if len(out) >= MAX_TAGS or depth > max_depth:
        return
    try:
        children = node.get_children()
    except Exception:  # noqa: BLE001 — a node may not be browsable
        return
    for child in children:
        if len(out) >= MAX_TAGS:
            return
        if not include_standard and _is_standard(child):
            continue
        try:
            nid = child.nodeid.to_string()
            name = child.read_browse_name().Name
            ncls = child.read_node_class().name
        except Exception:  # noqa: BLE001 — skip an unreadable child
            continue
        if nid in visited:
            continue
        visited.add(nid)
        if ncls == "Variable":
            out.append(_tag_descriptor(child, path, name))
        elif ncls == "Object":
            _walk_tags(child, (*path, name), depth + 1, max_depth, out,
                       include_standard, visited)


def discover_tags(target: Any, root: str = OBJECTS_NODE, max_depth: int = 6,
                  include_standard: bool = False) -> list[dict]:
    """[READ] Walk the OPC-UA address space and return enriched tag descriptors.

    Collects every Variable node under ``root`` (Object folders are recursed,
    other node classes ignored), each enriched with datatype / value / unit /
    semantic class / suggested alias. Bounded by MAX_TAGS / MAX_DISCOVERY_DEPTH.
    ``include_standard=False`` (default) skips OPC-UA namespace-0 infrastructure
    (the Server diagnostics subtree) so only real process tags are returned.
    """
    depth = max(1, min(int(max_depth), MAX_DISCOVERY_DEPTH))
    out: list[dict] = []
    with opcua_session(target) as client:
        root_node = client.get_node(root)
        _walk_tags(root_node, path=(), depth=1, max_depth=depth, out=out,
                   include_standard=include_standard, visited=set())
    return out


def build_tag_model(tags: list[dict]) -> dict:
    """Group discovered tags into an asset model + surface naming-quality issues.

    Pure function (no I/O) so it is unit-testable without a server. Returns assets
    (each with its tags + class breakdown) and a ``naming_quality`` report:
    duplicate aliases (collisions an operator must resolve before adopting) and
    cryptic names (too short / no semantic class).
    """
    assets: dict[str, list[dict]] = {}
    for t in tags:
        assets.setdefault(t.get("asset", ""), []).append(t)

    alias_counts: dict[str, int] = {}
    for t in tags:
        alias_counts[t.get("suggested_alias", "")] = (
            alias_counts.get(t.get("suggested_alias", ""), 0) + 1
        )
    alias_collisions = sorted(a for a, n in alias_counts.items() if a and n > 1)
    cryptic = sorted(
        t.get("browse_path", "") for t in tags
        if t.get("class") == "other" and len(str(t.get("browse_name", ""))) <= 3
    )

    asset_rows = [
        {
            "asset": asset or "(root)",
            "tag_count": len(items),
            "classes": _class_breakdown(items),
            "tags": items,
        }
        for asset, items in sorted(assets.items())
    ]
    return {
        "tag_count": len(tags),
        "asset_count": len(asset_rows),
        "assets": asset_rows,
        "naming_quality": {
            "alias_collisions": alias_collisions,
            "cryptic_names": cryptic,
            "verdict": "clean" if not alias_collisions and not cryptic else "review",
        },
        "note": "Advisory tag/asset model from the OPC-UA address space. Aliases are "
        "SUGGESTIONS (no server-side rename — that would be OT-dangerous).",
    }


def _class_breakdown(items: list[dict]) -> dict:
    """Count tags per semantic class within an asset (sorted, deterministic)."""
    counts: dict[str, int] = {}
    for t in items:
        counts[t.get("class", "other")] = counts.get(t.get("class", "other"), 0) + 1
    return dict(sorted(counts.items()))


def tag_discovery(target: Any, root: str = OBJECTS_NODE, max_depth: int = 6,
                  include_standard: bool = False) -> dict:
    """[READ] Discover OPC-UA tags and return the full asset/semantic model."""
    tags = discover_tags(target, root=root, max_depth=max_depth,
                         include_standard=include_standard)
    model = build_tag_model(tags)
    model["endpoint"] = s(getattr(target, "name", ""), 64)
    model["root"] = s(root, 64)
    return model


__all__ = [
    "classify_tag",
    "suggest_alias",
    "discover_tags",
    "build_tag_model",
    "tag_discovery",
]
