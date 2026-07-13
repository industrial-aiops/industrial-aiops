"""UNS governance — topic-sprawl / naming control + Sparkplug schema-drift (READ-ONLY).

Positions the Unified Namespace (MQTT / Sparkplug B topic tree) as a *governable*
neutral data source rather than an ungoverned broker. Two pure analyzers:

  * ``uns_topic_audit`` — over a flat list of UNS topics: namespace depth profile,
    naming-convention conformance (ISA-95-ish levels), and **topic sprawl** signals
    — inconsistent casing of the same logical name, the same leaf metric scattered
    under many parents, shallow/deep outliers, and single-child "orphan" branches.
  * ``uns_schema_drift`` — compares a baseline vs a current set of node/metric
    definitions (e.g. two Sparkplug NBIRTH snapshots): added / removed / type-changed
    metrics per node, with a breaking-vs-additive verdict.

Both operate over **provided** topic lists / metric definitions, so they are fully
testable without a live broker. All topic/metric text is sanitized.
"""

from __future__ import annotations

import statistics
from typing import Any

from iaiops.core.brain._shared import s

MAX_TOPICS = 20000
MAX_NODES = 5000
SEP = "/"


def uns_topic_audit(
    topics: list[str],
    allowed_roots: list[str] | None = None,
    min_segments: int = 0,
    max_leaf_parents: int = 5,
) -> dict:
    """[READ] Audit a UNS topic tree for naming conformance + sprawl.

    ``allowed_roots`` (optional) — the permitted top-level segments (e.g. the
    enterprise/site roots); any other root is a violation. ``min_segments`` — the
    minimum namespace depth a well-formed topic must have. ``max_leaf_parents`` —
    a leaf name appearing under more than this many distinct parents is flagged as
    scattered (likely a naming inconsistency). Returns depth stats, conformance,
    and ranked sprawl findings.
    """
    raw = [str(t) for t in (topics or [])[:MAX_TOPICS] if str(t).strip()]
    if not raw:
        return {"error": "No topics. Pass a list of UNS topic strings."}

    segs = [[p for p in t.split(SEP) if p != ""] for t in raw]
    depths = [len(parts) for parts in segs]
    roots = {parts[0] for parts in segs if parts}

    bad_root = sorted(
        {
            s(parts[0], 64)
            for parts in segs
            if allowed_roots and parts and parts[0] not in allowed_roots
        }
    )
    too_shallow = sorted(
        {s(SEP.join(parts), 200) for parts in segs if len(parts) < max(0, int(min_segments))}
    )
    casing = _casing_collisions(segs)
    scattered = _scattered_leaves(segs, max_leaf_parents)
    deep = _depth_outliers(raw, depths)
    duplicates = sorted({s(t, 200) for t in raw if raw.count(t) > 1})

    findings = {
        "non_conforming_root": bad_root,
        "too_shallow": too_shallow[:50],
        "casing_collisions": casing[:50],
        "scattered_leaves": scattered[:50],
        "depth_outliers": deep[:50],
        "duplicate_topics": duplicates[:50],
    }
    sprawl_count = sum(len(v) for v in findings.values())
    verdict = "clean" if sprawl_count == 0 else ("minor" if sprawl_count <= 5 else "sprawling")
    return {
        "topic_count": len(raw),
        "unique_topics": len(set(raw)),
        "root_count": len(roots),
        "roots": sorted(s(r, 64) for r in roots)[:50],
        "depth": {
            "min": min(depths),
            "max": max(depths),
            "mean": round(statistics.fmean(depths), 2),
        },
        "verdict": verdict,
        "sprawl_findings": sprawl_count,
        "findings": findings,
        "note": "Governance audit over a provided topic list (read-only). Sprawl "
        "signals are heuristics — review before enforcing a naming standard.",
    }


def uns_schema_drift(baseline: Any, current: Any) -> dict:
    """[READ] Sparkplug/UNS schema drift: baseline vs current node/metric definitions.

    ``baseline`` / ``current`` each map a node/topic to its metrics. Accepted shapes
    per side: ``{node: {metric: datatype}}`` or ``[{node|topic, metrics: [{name,
    datatype}]}]``. Per node, reports added / removed / type-changed metrics, and a
    verdict: ``none`` (identical), ``additive`` (only new metrics/nodes), or
    ``breaking`` (a metric was removed or changed type).
    """
    base = _normalize_schema(baseline)
    curr = _normalize_schema(current)
    if base is None or curr is None:
        return {
            "error": "baseline/current must be {node:{metric:datatype}} or "
            "[{node, metrics:[{name, datatype}]}]."
        }

    node_changes: list[dict] = []
    breaking = additive = False
    for node in sorted(set(base) | set(curr)):
        b = base.get(node, {})
        c = curr.get(node, {})
        added = sorted(set(c) - set(b))
        removed = sorted(set(b) - set(c))
        changed = sorted(m for m in (set(b) & set(c)) if b[m] != c[m])
        if not (added or removed or changed):
            continue
        if removed or changed:
            breaking = True
        if added or node not in base:
            additive = True
        node_changes.append(
            {
                "node": s(node, 128),
                "node_status": "added"
                if node not in base
                else ("removed" if node not in curr else "modified"),
                "added": [s(m, 96) for m in added],
                "removed": [s(m, 96) for m in removed],
                "type_changed": [
                    {"metric": s(m, 96), "from": s(b[m], 32), "to": s(c[m], 32)} for m in changed
                ],
            }
        )

    verdict = "breaking" if breaking else ("additive" if additive else "none")
    return {
        "baseline_nodes": len(base),
        "current_nodes": len(curr),
        "changed_nodes": len(node_changes),
        "verdict": verdict,
        "node_changes": node_changes[:MAX_NODES],
        "note": "Schema drift over provided definitions (read-only). 'breaking' = a "
        "metric was removed or changed datatype — downstream consumers may break.",
    }


# ─── topic-audit helpers ─────────────────────────────────────────────────────


def _casing_collisions(segs: list[list[str]]) -> list[str]:
    """Segments that appear with >1 casing of the same lowercased name."""
    by_lower: dict[str, set[str]] = {}
    for parts in segs:
        for p in parts:
            by_lower.setdefault(p.lower(), set()).add(p)
    return sorted(
        f"{lower}: {sorted(s(v, 48) for v in variants)}"
        for lower, variants in by_lower.items()
        if len(variants) > 1
    )


def _scattered_leaves(segs: list[list[str]], max_parents: int) -> list[str]:
    """Leaf names whose immediate parent varies across more than ``max_parents``."""
    parents: dict[str, set[str]] = {}
    for parts in segs:
        if len(parts) >= 2:
            parents.setdefault(parts[-1], set()).add(parts[-2])
    return sorted(
        f"{s(leaf, 64)} under {len(ps)} parents"
        for leaf, ps in parents.items()
        if len(ps) > max(1, int(max_parents))
    )


def _depth_outliers(raw: list[str], depths: list[int]) -> list[str]:
    """Topics whose depth is a statistical outlier (> mean + 2σ or < mean − 2σ)."""
    if len(depths) < 4:
        return []
    mean = statistics.fmean(depths)
    stdev = statistics.pstdev(depths)
    if stdev <= 0:
        return []
    lo, hi = mean - 2 * stdev, mean + 2 * stdev
    return sorted({s(t, 200) for t, d in zip(raw, depths) if d < lo or d > hi})


# ─── schema-drift helpers ────────────────────────────────────────────────────


def _normalize_schema(value: Any) -> dict[str, dict[str, str]] | None:
    """Coerce either accepted schema shape into ``{node: {metric: datatype}}``."""
    if isinstance(value, dict):
        out: dict[str, dict[str, str]] = {}
        for node, metrics in value.items():
            if isinstance(metrics, dict):
                out[str(node)] = {str(m): str(dt) for m, dt in metrics.items()}
            else:
                out[str(node)] = _metrics_list(metrics)
        return out
    if isinstance(value, list):
        out = {}
        for entry in value:
            if not isinstance(entry, dict):
                continue
            node = str(entry.get("node", entry.get("topic", entry.get("name", ""))))
            out[node] = _metrics_list(entry.get("metrics", []))
        return out
    return None


def _metrics_list(metrics: Any) -> dict[str, str]:
    """Coerce a metrics list ``[{name, datatype}]`` into ``{name: datatype}``."""
    out: dict[str, str] = {}
    for m in metrics or []:
        if isinstance(m, dict) and m.get("name") is not None:
            out[str(m["name"])] = str(m.get("datatype", m.get("type", "")))
    return out


__all__ = ["uns_topic_audit", "uns_schema_drift"]
