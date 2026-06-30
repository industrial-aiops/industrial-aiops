"""Cross-protocol unified asset / tag / alias model (pure, no I/O).

The two per-protocol tag models — OPC-UA address-space discovery
(:mod:`iaiops.connectors.opcua.discovery`) and Modbus register templates
(:mod:`iaiops.connectors.modbus.templates`) — each produce tags in their own
shape and vocabulary. A real site runs BOTH (and more), so the same physical
asset ("Line 1") shows up once per protocol with different names and no shared
alias. This module fuses per-protocol tag *feeds* into ONE asset/tag model:

  * every tag is normalized to a common shape and re-classified with the SAME
    semantic classifier the OPC-UA layer uses (:mod:`iaiops.core.brain.semantics`),
  * tags are grouped into assets ACROSS protocols (a ``Line1`` OPC-UA folder + a
    ``Line1`` Modbus block become one asset),
  * each tag gets a canonical cross-protocol alias ``<site>.<asset>.<class|name>``,
  * a cross-protocol naming-quality view surfaces alias collisions, the same
    physical quantity exposed by two protocols, and cryptic names.

It is **advisory and read-only** — the alias layer is a suggestion map, never a
server-side rename (which would be OT-dangerous). Inputs are plain tag dicts, so
the whole module is pure and unit-testable without any device.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s

# The shared semantic home — imported (not forked) so the unified layer and the
# OPC-UA connector classify + canonicalize identically.
from iaiops.core.brain.semantics import alias_segment, classify_tag, suggest_alias

MAX_FEEDS = 64
MAX_TAGS = 5000
CRYPTIC_MAX_LEN = 3


def _tag_name(raw: dict) -> str:
    """Pick a tag's display name across the supported feed shapes."""
    return str(raw.get("name") or raw.get("browse_name") or raw.get("tag") or "")


def _tag_ref(raw: dict) -> str:
    """Pick a tag's source ref (node id / register address / generic ref)."""
    for key in ("ref", "node_id", "address"):
        if raw.get(key) not in (None, ""):
            return s(str(raw[key]), 128)
    return ""


def _canonical_alias(site: str, asset: str, klass: str, name: str) -> str:
    """Build ``<site>.<asset>.<class|name>`` (class when meaningful, else name).

    Reuses the shared ``alias_segment`` canonicalization so a cross-protocol
    alias is sanitized exactly like a per-protocol ``suggest_alias``.
    """
    leaf = klass if klass and klass != "other" else name
    parts = [alias_segment(p) for p in (site, asset, leaf) if str(p)]
    return ".".join(parts) if parts else alias_segment(name)


def normalize_tag(raw: dict, *, protocol: str, source: str, asset: str = "",
                  site: str = "site") -> dict:
    """Normalize one per-protocol tag dict into the unified tag shape.

    Accepts OPC-UA discovery tags, Modbus template tags, or already-normalized
    tags. A tag's own ``asset`` wins over the feed-level ``asset``. The semantic
    class is taken as-is only if the source supplied a real one, otherwise it is
    (re)inferred with the SHARED classifier so every protocol uses one taxonomy.
    """
    name = s(_tag_name(raw), 128)
    own_asset = str(raw.get("asset") or asset or "")
    provided = str(raw.get("class") or raw.get("klass") or "")
    klass = provided if provided and provided != "other" else classify_tag(name)
    return {
        "protocol": s(str(protocol), 24),
        "source": s(str(source), 64),
        "name": name,
        "ref": _tag_ref(raw),
        "asset": s(own_asset, 200),
        "unit": s(str(raw.get("unit") or ""), 32),
        "value": raw.get("value"),
        "klass": s(klass, 32),
        "suggested_alias": suggest_alias(own_asset, name),
        "canonical_alias": _canonical_alias(site, own_asset, klass, name),
    }


def _validate_feeds(feeds: Any) -> list[dict]:
    """Validate the feeds payload at the boundary (fail fast, teaching errors)."""
    if not isinstance(feeds, list):
        raise ValueError(
            "cross_protocol_asset_model expects a list of feed objects "
            "[{protocol, source, asset?, tags:[...]}], got "
            f"{type(feeds).__name__}."
        )
    for i, feed in enumerate(feeds[:MAX_FEEDS]):
        if not isinstance(feed, dict):
            raise ValueError(f"feed #{i} must be an object, got {type(feed).__name__}.")
        if not str(feed.get("protocol") or ""):
            raise ValueError(f"feed #{i} is missing a 'protocol' (e.g. 'opcua', 'modbus').")
    return list(feeds[:MAX_FEEDS])


def _normalize_all(feeds: list[dict], site: str) -> list[dict]:
    """Flatten + normalize every tag across all feeds (bounded by MAX_TAGS)."""
    out: list[dict] = []
    for feed in feeds:
        protocol = str(feed.get("protocol"))
        source = str(feed.get("source") or protocol)
        feed_asset = str(feed.get("asset") or "")
        for raw in feed.get("tags") or []:
            if len(out) >= MAX_TAGS:
                return out
            if isinstance(raw, dict):
                out.append(normalize_tag(raw, protocol=protocol, source=source,
                                         asset=feed_asset, site=site))
    return out


def _group_assets(tags: list[dict]) -> list[dict]:
    """Group normalized tags into assets, recording the protocols that touch each."""
    buckets: dict[str, list[dict]] = {}
    for t in tags:
        buckets.setdefault(t["asset"], []).append(t)
    rows = []
    for asset, items in sorted(buckets.items()):
        rows.append({
            "asset": asset or "(unassigned)",
            "protocols": sorted({t["protocol"] for t in items}),
            "tag_count": len(items),
            "classes": _class_breakdown(items),
            "tags": items,
        })
    return rows


def _class_breakdown(items: list[dict]) -> dict:
    """Count tags per semantic class within an asset (sorted, deterministic)."""
    counts: dict[str, int] = {}
    for t in items:
        counts[t["klass"]] = counts.get(t["klass"], 0) + 1
    return dict(sorted(counts.items()))


def _alias_collisions(tags: list[dict]) -> list[dict]:
    """Canonical aliases claimed by more than one tag (operator must disambiguate)."""
    groups: dict[str, list[dict]] = {}
    for t in tags:
        groups.setdefault(t["canonical_alias"], []).append(t)
    collisions = [
        {
            "alias": alias,
            "count": len(items),
            "protocols": sorted({t["protocol"] for t in items}),
            "refs": sorted(f"{t['protocol']}:{t['ref'] or t['name']}" for t in items),
        }
        for alias, items in groups.items()
        if alias and len(items) > 1
    ]
    return sorted(collisions, key=lambda c: c["alias"])


def _cross_protocol_overlaps(tags: list[dict]) -> list[dict]:
    """Same physical quantity (class) on one asset exposed by ≥2 protocols."""
    groups: dict[tuple[str, str], set[str]] = {}
    for t in tags:
        if t["klass"] and t["klass"] != "other":
            groups.setdefault((t["asset"], t["klass"]), set()).add(t["protocol"])
    overlaps = [
        {"asset": asset or "(unassigned)", "klass": klass, "protocols": sorted(protos)}
        for (asset, klass), protos in groups.items()
        if len(protos) > 1
    ]
    return sorted(overlaps, key=lambda o: (o["asset"], o["klass"]))


def _cryptic_names(tags: list[dict]) -> list[str]:
    """Tags with no semantic class and a too-short name (a naming smell)."""
    return sorted({
        f"{t['asset']}/{t['name']}" if t["asset"] else t["name"]
        for t in tags
        if t["klass"] == "other" and len(t["name"]) <= CRYPTIC_MAX_LEN and t["name"]
    })


def cross_protocol_asset_model(feeds: Any, site: str = "site") -> dict:
    """[READ] Fuse per-protocol tag feeds into ONE unified asset/tag/alias model.

    ``feeds`` is a list of ``{protocol, source, asset?, tags:[...]}`` where each
    tag is an OPC-UA discovery descriptor, a Modbus template tag, or an already
    normalized tag. Returns grouped assets (across protocols), canonical aliases,
    and a cross-protocol ``naming_quality`` view. Pure + advisory — aliases are
    SUGGESTIONS, never a server-side rename.
    """
    valid = _validate_feeds(feeds)
    tags = _normalize_all(valid, site)
    assets = _group_assets(tags)
    collisions = _alias_collisions(tags)
    overlaps = _cross_protocol_overlaps(tags)
    cryptic = _cryptic_names(tags)
    return {
        "site": s(str(site), 64),
        "protocols": sorted({t["protocol"] for t in tags}),
        "tag_count": len(tags),
        "asset_count": len(assets),
        "assets": assets,
        "naming_quality": {
            "alias_collisions": collisions,
            "cross_protocol_overlaps": overlaps,
            "cryptic_names": cryptic,
            "verdict": "clean" if not (collisions or cryptic) else "review",
        },
        "note": "Advisory cross-protocol asset/tag model fused from per-protocol "
        "feeds. Aliases are SUGGESTIONS (no server-side rename — OT-dangerous). "
        "cross_protocol_overlaps flags the same physical quantity exposed by two "
        "protocols (often the same sensor seen twice).",
    }


__all__ = ["cross_protocol_asset_model", "normalize_tag", "classify_tag", "suggest_alias"]
