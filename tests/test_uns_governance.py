"""UNS governance tests over synthetic topic lists + schema snapshots (no broker).

Exercises topic-sprawl signals (casing collisions, scattered leaves, depth
outliers, non-conforming roots, duplicates) and Sparkplug schema-drift
classification (none / additive / breaking) across both accepted input shapes.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain import uns_governance as uns

# ─── uns_topic_audit ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_topics_error():
    assert "error" in uns.uns_topic_audit([])


@pytest.mark.unit
def test_clean_tree_is_clean():
    topics = [
        "Ent/SiteA/Area1/Line1/temperature",
        "Ent/SiteA/Area1/Line1/pressure",
        "Ent/SiteA/Area1/Line2/temperature",
    ]
    out = uns.uns_topic_audit(topics, allowed_roots=["Ent"], min_segments=3)
    assert out["verdict"] == "clean"
    assert out["sprawl_findings"] == 0
    assert out["root_count"] == 1


@pytest.mark.unit
def test_casing_collision_flagged():
    topics = ["Ent/SiteA/Line1/Temp", "Ent/siteA/Line1/temp"]
    out = uns.uns_topic_audit(topics)
    collisions = " ".join(out["findings"]["casing_collisions"])
    assert "sitea" in collisions  # SiteA vs siteA
    assert "temp" in collisions   # Temp vs temp
    assert out["verdict"] in ("minor", "sprawling")


@pytest.mark.unit
def test_non_conforming_root_flagged():
    topics = ["Ent/SiteA/x", "Rogue/SiteB/y"]
    out = uns.uns_topic_audit(topics, allowed_roots=["Ent"])
    assert "Rogue" in out["findings"]["non_conforming_root"]


@pytest.mark.unit
def test_too_shallow_flagged():
    topics = ["Ent/SiteA/Area1/Line1/temp", "flat"]
    out = uns.uns_topic_audit(topics, min_segments=3)
    assert "flat" in out["findings"]["too_shallow"]


@pytest.mark.unit
def test_scattered_leaf_flagged():
    # 'status' appears under 6 distinct parents → scattered (> default max 5)
    topics = [f"Ent/Site/Area/L{i}/status" for i in range(6)]
    out = uns.uns_topic_audit(topics)
    scattered = " ".join(out["findings"]["scattered_leaves"])
    assert "status" in scattered


@pytest.mark.unit
def test_duplicate_topics_flagged():
    topics = ["Ent/A/x", "Ent/A/x", "Ent/A/y"]
    out = uns.uns_topic_audit(topics)
    assert "Ent/A/x" in out["findings"]["duplicate_topics"]
    assert out["unique_topics"] == 2


# ─── uns_schema_drift ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_drift():
    schema = {"N1": {"temp": "Float", "rpm": "Int32"}}
    out = uns.uns_schema_drift(schema, dict(schema))
    assert out["verdict"] == "none"
    assert out["changed_nodes"] == 0


@pytest.mark.unit
def test_additive_drift():
    base = {"N1": {"temp": "Float"}}
    curr = {"N1": {"temp": "Float", "rpm": "Float"}, "N2": {"x": "Boolean"}}
    out = uns.uns_schema_drift(base, curr)
    assert out["verdict"] == "additive"
    n1 = next(c for c in out["node_changes"] if c["node"] == "N1")
    assert n1["added"] == ["rpm"]


@pytest.mark.unit
def test_breaking_drift_on_removed_metric():
    base = {"N1": {"temp": "Float", "rpm": "Int32"}}
    curr = {"N1": {"temp": "Float"}}
    out = uns.uns_schema_drift(base, curr)
    assert out["verdict"] == "breaking"
    n1 = out["node_changes"][0]
    assert n1["removed"] == ["rpm"]


@pytest.mark.unit
def test_breaking_drift_on_type_change():
    base = {"N1": {"temp": "Float"}}
    curr = {"N1": {"temp": "Int32"}}
    out = uns.uns_schema_drift(base, curr)
    assert out["verdict"] == "breaking"
    tc = out["node_changes"][0]["type_changed"][0]
    assert tc["from"] == "Float" and tc["to"] == "Int32"


@pytest.mark.unit
def test_schema_drift_accepts_list_shape():
    base = [{"node": "N1", "metrics": [{"name": "temp", "datatype": "Float"}]}]
    curr = [{"node": "N1", "metrics": [{"name": "temp", "datatype": "Float"},
                                       {"name": "rpm", "datatype": "Int32"}]}]
    out = uns.uns_schema_drift(base, curr)
    assert out["verdict"] == "additive"
    assert out["node_changes"][0]["added"] == ["rpm"]


@pytest.mark.unit
def test_schema_drift_bad_input():
    assert "error" in uns.uns_schema_drift(42, {"N1": {}})
