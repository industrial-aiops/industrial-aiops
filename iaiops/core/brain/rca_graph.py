"""Causal-graph projection of an RCA verdict (pure re-shape, no new reasoning).

:func:`iaiops.core.brain.rca.downtime_rca` already produces the verdict: ranked
``hypotheses``, each with a ``confidence`` (the noisy-OR aggregate) and cited
``evidence`` items carrying the per-signal contribution ``weight``. That shape is
*flat* — good for a report, awkward for a frontend that wants to draw the
signal → cause → downtime chain.

This module RE-PROJECTS a finished verdict into a ``{nodes, edges}`` causal
graph. It performs **no** correlation, scoring, or inference of its own — every
node is a signal/cause already present in the verdict, and every edge weight is a
number the engine already computed:

  * ``signal → cause`` edges carry the evidence item's contribution ``weight``
    (the proximity- and cause-weight-scaled support the verdict already lists), and
  * ``cause → symptom`` edges carry the hypothesis ``confidence`` (the attribution
    strength the verdict already computed via noisy-OR).

Because it only reshapes existing data, the graph is faithful by construction:
no orphan nodes, no fabricated edges, and every weight traces back to the verdict.
An empty (no-hypothesis / error) verdict yields an empty graph rather than a lone
orphan symptom node.
"""

from __future__ import annotations

from typing import Any

# Node kinds and edge relations — a small, closed vocabulary a frontend can style.
NODE_KIND_SIGNAL = "signal"
NODE_KIND_CAUSE = "cause"
NODE_KIND_SYMPTOM = "symptom"
RELATION_SUPPORTS = "supports"  # signal → cause  (weight = evidence contribution)
RELATION_ATTRIBUTED = "attributed_to"  # cause → symptom (weight = hypothesis confidence)

# The single symptom node every verdict points at: the downtime/incident itself.
SYMPTOM_ID = "symptom:downtime"


def build_causal_graph(verdict: dict[str, Any]) -> dict[str, Any]:
    """Re-project a computed RCA ``verdict`` into a ``{nodes, edges, mermaid, meta}`` graph.

    Pure reshape of the verdict's own ``hypotheses``/``evidence`` — nothing is
    re-derived. ``signal → cause`` edge weights are the evidence contribution
    weights and ``cause → symptom`` edge weights are the hypothesis confidences,
    both copied verbatim. A verdict with no hypotheses (thin evidence or an input
    error) yields an empty graph, not a dangling node. The input is never mutated.
    """
    hyps = verdict.get("hypotheses") if isinstance(verdict, dict) else None
    hypotheses = [h for h in (hyps or []) if isinstance(h, dict)]
    if not hypotheses:
        return _empty_graph(verdict)

    window = verdict.get("window") if isinstance(verdict, dict) else None
    primary = verdict.get("primary_cause") if isinstance(verdict, dict) else None
    primary_cause = primary.get("cause") if isinstance(primary, dict) else None

    nodes: dict[str, dict] = {SYMPTOM_ID: _symptom_node(window)}
    edges: list[dict] = []

    for hyp in hypotheses:
        cause = str(hyp.get("cause"))
        cause_id = f"cause:{cause}"
        nodes[cause_id] = _cause_node(cause_id, cause, hyp, is_primary=cause == primary_cause)
        # cause → symptom: the attribution strength IS the hypothesis confidence.
        edges.append(_edge(cause_id, SYMPTOM_ID, hyp.get("confidence"), RELATION_ATTRIBUTED))
        for ev in hyp.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            sig_id = _signal_id(ev)
            nodes[sig_id] = _merge_signal_node(nodes.get(sig_id), sig_id, ev)
            # signal → cause: the edge weight IS the evidence contribution weight.
            edges.append(_edge(sig_id, cause_id, ev.get("weight"), RELATION_SUPPORTS))

    node_list = list(nodes.values())
    return {
        "nodes": node_list,
        "edges": edges,
        "mermaid": to_mermaid(node_list, edges),
        "meta": {
            "verdict": verdict.get("verdict"),
            "primary_cause": primary_cause,
            "node_count": len(node_list),
            "edge_count": len(edges),
        },
    }


def causal_graph_mermaid(graph: dict[str, Any]) -> str:
    """Render a built graph as a Mermaid ``flowchart`` string (paste-ready for a UI)."""
    return to_mermaid(graph.get("nodes") or [], graph.get("edges") or [])


def causal_graph_dot(graph: dict[str, Any]) -> str:
    """Render a built graph as a Graphviz DOT ``digraph`` string."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    id_map = {n["id"]: f"n{i}" for i, n in enumerate(nodes)}
    lines = ["digraph rca {", "  rankdir=LR;", "  node [fontsize=10];"]
    for node in nodes:
        nid = id_map[node["id"]]
        lines.append(f'  "{nid}" [label="{_dot_label(node)}", shape={_dot_shape(node)}];')
    for edge in edges:
        frm, to = id_map.get(edge["from"]), id_map.get(edge["to"])
        if frm is None or to is None:
            continue
        label = _fmt_weight(edge.get("weight"))
        attr = f' [label="{label}"]' if label else ""
        lines.append(f'  "{frm}" -> "{to}"{attr};')
    lines.append("}")
    return "\n".join(lines) + "\n"


# ─── node / edge construction ────────────────────────────────────────────────


def _empty_graph(verdict: dict[str, Any]) -> dict[str, Any]:
    """A verdict with nothing to attribute maps to an empty (orphan-free) graph."""
    v = verdict.get("verdict") if isinstance(verdict, dict) else None
    return {
        "nodes": [],
        "edges": [],
        "mermaid": "flowchart LR\n",
        "meta": {"verdict": v, "primary_cause": None, "node_count": 0, "edge_count": 0},
    }


def _symptom_node(window: dict | None) -> dict:
    win = window if isinstance(window, dict) else {}
    return {
        "id": SYMPTOM_ID,
        "kind": NODE_KIND_SYMPTOM,
        "label": _symptom_label(win),
        "score": None,
        "asset": win.get("asset") or None,
        "category": win.get("category"),
        "start": win.get("start"),
        "end": win.get("end"),
        "duration_s": win.get("duration_s"),
    }


def _symptom_label(win: dict) -> str:
    parts = ["downtime"]
    for key in ("asset", "category"):
        value = win.get(key)
        if value:
            parts.append(str(value))
    return " · ".join(parts)


def _cause_node(cause_id: str, cause: str, hyp: dict, *, is_primary: bool) -> dict:
    return {
        "id": cause_id,
        "kind": NODE_KIND_CAUSE,
        "label": cause,
        "score": hyp.get("confidence"),
        "confidence_band": hyp.get("confidence_band"),
        "recommended_action": hyp.get("recommended_action"),
        "is_primary": bool(is_primary),
    }


def _signal_id(ev: dict) -> str:
    return f"signal:{ev.get('signal')}:{ev.get('ref')}"


def _signal_node(sig_id: str, ev: dict) -> dict:
    ref, signal = ev.get("ref"), ev.get("signal")
    node = {
        "id": sig_id,
        "kind": NODE_KIND_SIGNAL,
        "label": str(ref) if ref else str(signal),
        "signal": signal,
        "ref": ref,
        "score": ev.get("weight"),
        "detail": ev.get("detail"),
    }
    # Preserve the temporal localization the verdict already carries, when present.
    if ev.get("at") is not None:
        node["at"] = ev.get("at")
    if ev.get("lead_time_s") is not None:
        node["lead_time_s"] = ev.get("lead_time_s")
    return node


def _merge_signal_node(existing: dict | None, sig_id: str, ev: dict) -> dict:
    """Dedupe one physical signal cited by >1 cause; its node score is the strongest.

    The authoritative per-cause contribution stays on each ``signal → cause`` edge;
    the node's ``score`` is only the max of those weights, a display convenience
    (still a number already in the verdict — no new value is invented).
    """
    if existing is None:
        return _signal_node(sig_id, ev)
    best = _max_weight(existing.get("score"), ev.get("weight"))
    if best == existing.get("score"):
        return existing
    return {**existing, "score": best}


def _max_weight(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _edge(frm: str, to: str, weight: Any, relation: str) -> dict:
    return {"from": frm, "to": to, "weight": weight, "relation": relation}


# ─── text exporters (Mermaid / DOT) ──────────────────────────────────────────

_MERMAID_CLASSDEFS = (
    "  classDef signal fill:#eef2ff,stroke:#6675c4,color:#111;",
    "  classDef cause fill:#fdecec,stroke:#c46666,color:#111;",
    "  classDef symptom fill:#eafaf0,stroke:#4a9d6a,color:#111;",
)


def to_mermaid(nodes: list[dict], edges: list[dict]) -> str:
    """Build a Mermaid ``flowchart LR`` from node/edge lists (ids re-labelled n0, n1…)."""
    lines = ["flowchart LR"]
    id_map = {n["id"]: f"n{i}" for i, n in enumerate(nodes)}
    for node in nodes:
        lines.append(f"  {id_map[node['id']]}{_mermaid_shape(node)}:::{node['kind']}")
    for edge in edges:
        frm, to = id_map.get(edge["from"]), id_map.get(edge["to"])
        if frm is None or to is None:
            continue
        label = _fmt_weight(edge.get("weight"))
        lines.append(f"  {frm} -->|{label}| {to}" if label else f"  {frm} --> {to}")
    lines.extend(_MERMAID_CLASSDEFS)
    return "\n".join(lines) + "\n"


def _mermaid_shape(node: dict) -> str:
    label = _mermaid_label(node)
    kind = node["kind"]
    if kind == NODE_KIND_CAUSE:
        return '(["' + label + '"])'
    if kind == NODE_KIND_SYMPTOM:
        return '{{"' + label + '"}}'
    return '["' + label + '"]'


def _mermaid_label(node: dict) -> str:
    label = _sanitize(str(node.get("label", "")))
    score = node.get("score")
    if node["kind"] == NODE_KIND_CAUSE and isinstance(score, (int, float)):
        return f"{label}<br/>conf {round(score, 3)}"
    return label


def _sanitize(text: str) -> str:
    """Neutralize characters that would break a Mermaid quoted label."""
    return text.replace('"', "'").replace("\n", " ").replace("|", "/")


def _dot_shape(node: dict) -> str:
    return {NODE_KIND_CAUSE: "ellipse", NODE_KIND_SYMPTOM: "hexagon"}.get(node["kind"], "box")


def _dot_label(node: dict) -> str:
    label = str(node.get("label", "")).replace('"', "'").replace("\n", " ")
    score = node.get("score")
    if node["kind"] == NODE_KIND_CAUSE and isinstance(score, (int, float)):
        return f"{label} ({round(score, 3)})"
    return label


def _fmt_weight(weight: Any) -> str:
    if not isinstance(weight, (int, float)):
        return ""
    return f"{round(float(weight), 3)}"


__all__ = [
    "build_causal_graph",
    "causal_graph_mermaid",
    "causal_graph_dot",
    "to_mermaid",
    "NODE_KIND_SIGNAL",
    "NODE_KIND_CAUSE",
    "NODE_KIND_SYMPTOM",
    "RELATION_SUPPORTS",
    "RELATION_ATTRIBUTED",
    "SYMPTOM_ID",
]
