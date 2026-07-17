"""Causal-graph export tests — the graph is a FAITHFUL re-projection of the verdict.

No new reasoning is allowed in the graph layer, so every assertion here ties a
node/edge back to a value the verdict already computed:

  * ``signal → cause`` edge weight == the evidence item's contribution weight,
  * ``cause → symptom`` edge weight == the hypothesis confidence,
  * no orphan nodes (every node touches an edge; every edge endpoint is a node),
  * no fabricated causes/signals (graph nodes ⊆ verdict hypotheses/evidence),
  * an empty/error verdict yields an empty graph (never a dangling node),
  * the pure builder never mutates its input verdict.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain import rca, rca_graph
from mcp_server.tools.diagnostics_tools import downtime_root_cause
from mcp_server.tools.downtime_tools import downtime_triage as downtime_triage_tool

ONSET = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _window(**extra) -> dict:
    return {
        "start": _iso(ONSET),
        "end": _iso(ONSET + timedelta(minutes=5)),
        "asset": "line1",
        **extra,
    }


def _single(**kw) -> dict:
    """A dominant single-cause verdict (mechanical_fault: alarm + tag agree)."""
    alarms = [
        {
            "source": "M1_DRIVE",
            "timestamp": _iso(ONSET - timedelta(seconds=8)),
            "message": "motor overload trip",
        }
    ]
    tags = [{"ref": "DRV1.Torque", "samples": [10, 11, 99, 99], "warn_high": 50, "alarm_high": 80}]
    return rca.downtime_rca(
        _window(), alarms=alarms, tags=tags, dataflow={"verdict": "healthy"}, **kw
    )


def _multi(**kw) -> dict:
    """A two-cause verdict (mechanical alarm + sensor-stale dataflow)."""
    alarms = [
        {
            "source": "M1",
            "timestamp": _iso(ONSET - timedelta(seconds=5)),
            "message": "mechanical jam",
        }
    ]
    return rca.downtime_rca(
        _window(),
        alarms=alarms,
        dataflow={"verdict": "comms_ok_value_stale", "diagnosis": "stale"},
        **kw,
    )


def _supports(graph: dict) -> list[dict]:
    return [e for e in graph["edges"] if e["relation"] == rca_graph.RELATION_SUPPORTS]


def _attributions(graph: dict) -> list[dict]:
    return [e for e in graph["edges"] if e["relation"] == rca_graph.RELATION_ATTRIBUTED]


def _by_id(graph: dict) -> dict[str, dict]:
    return {n["id"]: n for n in graph["nodes"]}


# ─── include_graph flag plumbing ─────────────────────────────────────────────


@pytest.mark.unit
def test_graph_absent_by_default():
    assert "graph" not in _single()


@pytest.mark.unit
def test_include_graph_attaches_block_without_changing_verdict():
    plain = _single()
    withg = _single(include_graph=True)
    assert "graph" in withg
    # The verdict itself is byte-identical; the graph is purely additive.
    assert {k: withg[k] for k in plain} == plain
    g = withg["graph"]
    assert set(g) >= {"nodes", "edges", "mermaid", "meta"}


# ─── faithfulness: edge weights == already-computed scores ───────────────────


@pytest.mark.unit
def test_supports_edge_weight_equals_evidence_contribution():
    v = _multi(include_graph=True)
    g = v["graph"]
    nodes = _by_id(g)
    # (cause, signal, ref) -> contribution weight, straight from the verdict.
    ev_weight = {
        (h["cause"], e["signal"], e["ref"]): e["weight"]
        for h in v["hypotheses"]
        for e in h["evidence"]
    }
    seen = 0
    for edge in _supports(g):
        src, dst = nodes[edge["from"]], nodes[edge["to"]]
        assert src["kind"] == "signal" and dst["kind"] == "cause"
        assert edge["weight"] == ev_weight[(dst["label"], src["signal"], src["ref"])]
        seen += 1
    assert seen == sum(len(h["evidence"]) for h in v["hypotheses"])


@pytest.mark.unit
def test_attribution_edge_weight_equals_hypothesis_confidence():
    v = _multi(include_graph=True)
    g = v["graph"]
    nodes = _by_id(g)
    conf = {h["cause"]: h["confidence"] for h in v["hypotheses"]}
    attributions = _attributions(g)
    for edge in attributions:
        src, dst = nodes[edge["from"]], nodes[edge["to"]]
        assert src["kind"] == "cause" and dst["kind"] == "symptom"
        assert edge["weight"] == conf[src["label"]]
    assert len(attributions) == len(v["hypotheses"])


@pytest.mark.unit
def test_cause_node_score_is_the_confidence():
    v = _single(include_graph=True)
    conf = {h["cause"]: h["confidence"] for h in v["hypotheses"]}
    for node in v["graph"]["nodes"]:
        if node["kind"] == "cause":
            assert node["score"] == conf[node["label"]]


# ─── faithfulness: no orphans, no fabrication ────────────────────────────────


@pytest.mark.unit
def test_no_orphan_nodes_and_no_dangling_edges():
    g = _multi(include_graph=True)["graph"]
    node_ids = {n["id"] for n in g["nodes"]}
    referenced = {e["from"] for e in g["edges"]} | {e["to"] for e in g["edges"]}
    # Every node touches an edge AND every edge endpoint is a real node.
    assert node_ids == referenced


@pytest.mark.unit
def test_graph_causes_are_exactly_the_verdict_causes():
    v = _multi(include_graph=True)
    verdict_causes = {h["cause"] for h in v["hypotheses"]}
    graph_causes = {n["label"] for n in v["graph"]["nodes"] if n["kind"] == "cause"}
    assert graph_causes == verdict_causes


@pytest.mark.unit
def test_graph_signals_are_exactly_the_cited_evidence():
    v = _multi(include_graph=True)
    cited = {(e["signal"], e["ref"]) for h in v["hypotheses"] for e in h["evidence"]}
    graph_signals = {(n["signal"], n["ref"]) for n in v["graph"]["nodes"] if n["kind"] == "signal"}
    assert graph_signals == cited  # nothing invented, nothing dropped


@pytest.mark.unit
def test_exactly_one_symptom_node_with_incoming_attributions():
    g = _multi(include_graph=True)["graph"]
    symptoms = [n for n in g["nodes"] if n["kind"] == "symptom"]
    assert len(symptoms) == 1
    sid = symptoms[0]["id"]
    assert all(e["to"] == sid for e in _attributions(g))
    assert symptoms[0]["asset"] == "line1"


@pytest.mark.unit
def test_primary_cause_is_flagged_uniquely():
    v = _single(include_graph=True)
    assert v["primary_cause"] is not None
    primary = v["primary_cause"]["cause"]
    flagged = [
        n["label"] for n in v["graph"]["nodes"] if n["kind"] == "cause" and n.get("is_primary")
    ]
    assert flagged == [primary]


# ─── thin / error verdicts → empty graph (never a lone orphan) ───────────────


@pytest.mark.unit
def test_no_evidence_yields_empty_graph():
    v = rca.downtime_rca(_window(), include_graph=True)
    assert v["verdict"] == "insufficient_evidence"
    assert v["graph"]["nodes"] == [] and v["graph"]["edges"] == []
    assert v["graph"]["meta"]["node_count"] == 0


@pytest.mark.unit
def test_error_verdict_yields_empty_graph():
    v = rca.downtime_rca({"asset": "x"}, include_graph=True)  # missing start
    assert "error" in v
    assert v["graph"]["nodes"] == [] and v["graph"]["edges"] == []


@pytest.mark.unit
def test_flood_only_graph_still_mirrors_hypotheses():
    # A pure flood is context, not a localized cause: verdict is insufficient but
    # the alarm_flood hypothesis exists, so the graph must mirror it faithfully.
    flood = [
        {
            "source": f"X{i % 3}",
            "timestamp": _iso(ONSET - timedelta(seconds=i)),
            "message": "high",
            "state": "ACTIVE",
        }
        for i in range(60)
    ]
    v = rca.downtime_rca(_window(), alarms=flood, include_graph=True)
    graph_causes = {n["label"] for n in v["graph"]["nodes"] if n["kind"] == "cause"}
    assert graph_causes == {h["cause"] for h in v["hypotheses"]}
    assert "alarm_flood" in graph_causes
    # Even here, no orphans.
    node_ids = {n["id"] for n in v["graph"]["nodes"]}
    referenced = {e["from"] for e in v["graph"]["edges"]} | {e["to"] for e in v["graph"]["edges"]}
    assert node_ids == referenced


# ─── the builder is a pure re-projection ─────────────────────────────────────


@pytest.mark.unit
def test_build_causal_graph_does_not_mutate_the_verdict():
    v = _single()  # no graph attached
    snapshot = copy.deepcopy(v)
    g = rca.build_causal_graph(v)
    assert v == snapshot  # input untouched
    assert g["nodes"] and g["edges"]
    assert g["meta"]["node_count"] == len(g["nodes"])
    assert g["meta"]["edge_count"] == len(g["edges"])


@pytest.mark.unit
def test_edge_counts_match_verdict_structure():
    v = _multi(include_graph=True)
    g = v["graph"]
    assert len(_supports(g)) == sum(len(h["evidence"]) for h in v["hypotheses"])
    assert len(_attributions(g)) == len(v["hypotheses"])


# ─── text exporters (Mermaid / DOT) ──────────────────────────────────────────


@pytest.mark.unit
def test_mermaid_export_is_flowchart_naming_the_cause():
    v = _single(include_graph=True)
    mermaid = v["graph"]["mermaid"]
    assert isinstance(mermaid, str) and mermaid.startswith("flowchart LR")
    assert "mechanical_fault" in mermaid
    # convenience wrapper agrees with the inline string
    assert rca.causal_graph_mermaid(v["graph"]) == mermaid


@pytest.mark.unit
def test_dot_export_is_a_digraph_with_edges():
    v = _single(include_graph=True)
    dot = rca.causal_graph_dot(v["graph"])
    assert dot.startswith("digraph rca {") and dot.rstrip().endswith("}")
    assert "->" in dot
    assert "mechanical_fault" in dot


@pytest.mark.unit
def test_empty_graph_exports_are_safe_strings():
    g = rca.build_causal_graph(rca.downtime_rca(_window()))  # thin → empty graph
    assert rca.causal_graph_mermaid(g).startswith("flowchart")
    assert rca.causal_graph_dot(g).startswith("digraph")


# ─── tool wiring: existing tools carry the flag (zero new @mcp.tool) ─────────


@pytest.mark.unit
def test_downtime_root_cause_tool_threads_include_graph():
    alarms = [
        {
            "source": "M1_DRIVE",
            "timestamp": _iso(ONSET - timedelta(seconds=8)),
            "message": "motor overload trip",
        }
    ]
    plain = downtime_root_cause(window=_window(), alarms=alarms)
    withg = downtime_root_cause(window=_window(), alarms=alarms, include_graph=True)
    assert "graph" not in plain
    assert withg["graph"]["nodes"] and withg["graph"]["edges"]
    cause_labels = {n["label"] for n in withg["graph"]["nodes"] if n["kind"] == "cause"}
    assert "mechanical_fault" in cause_labels


@pytest.mark.unit
def test_downtime_triage_tool_surfaces_graph_in_rca_block():
    alarms = [
        {
            "source": "M1_DRIVE",
            "timestamp": _iso(ONSET - timedelta(seconds=8)),
            "message": "motor overload trip",
        }
    ]
    plain = downtime_triage_tool(window=_window(), alarms=alarms)
    withg = downtime_triage_tool(window=_window(), alarms=alarms, include_graph=True)
    assert "graph" not in plain["rca"]
    assert "graph" in withg["rca"]
    assert withg["rca"]["graph"]["edges"]
