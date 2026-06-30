"""Cross-protocol unified asset/tag model (pure brain layer).

Proves: per-protocol tag feeds (OPC-UA discovery + Modbus template shapes) are
normalized, grouped into ONE asset model across protocols, given canonical
``<site>.<asset>.<class_or_name>`` aliases, and that the cross-protocol naming
view surfaces alias collisions, same-quantity-two-protocols overlaps and cryptic
names. Also pins that the SAME ``classify_tag`` / ``suggest_alias`` are shared by
the OPC-UA connector and this layer (no divergent fork).
"""

from __future__ import annotations

import pytest

from iaiops.connectors.opcua import discovery as disc
from iaiops.core.brain import asset_model as am
from iaiops.core.brain import semantics

# ── shared-semantics (no drift) ───────────────────────────────────────────────

@pytest.mark.unit
def test_shared_classifier_and_alias_are_the_same_object():
    """The connector and the unified layer must use the SAME functions."""
    assert disc.classify_tag is semantics.classify_tag
    assert disc.suggest_alias is semantics.suggest_alias
    assert am.classify_tag is semantics.classify_tag
    assert am.suggest_alias is semantics.suggest_alias


# ── normalization ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_normalize_opcua_tag_preserves_class_and_alias():
    raw = {"browse_name": "Temperature", "asset": "Line1", "class": "temperature",
           "unit": "degC", "node_id": "ns=2;i=5", "value": 85.0}
    t = am.normalize_tag(raw, protocol="opcua", source="line1")
    assert t["protocol"] == "opcua"
    assert t["source"] == "line1"
    assert t["name"] == "Temperature"
    assert t["asset"] == "Line1"
    assert t["klass"] == "temperature"
    assert t["ref"] == "ns=2;i=5"
    assert t["canonical_alias"] == "site.line1.temperature"


@pytest.mark.unit
def test_normalize_modbus_tag_infers_class_via_shared_classifier():
    """A Modbus template tag has no 'class' → classified by the SAME classifier."""
    raw = {"tag": "voltage_l1", "address": 0, "unit": "V", "value": 230.1}
    t = am.normalize_tag(raw, protocol="modbus", source="meter1", asset="Line1")
    assert t["name"] == "voltage_l1"
    assert t["klass"] == "voltage"  # inferred, not provided
    assert t["asset"] == "Line1"
    assert t["ref"] == "0"
    assert t["canonical_alias"] == "site.line1.voltage"


@pytest.mark.unit
def test_normalize_uses_name_when_class_other():
    raw = {"tag": "aux_relay", "address": 7}
    t = am.normalize_tag(raw, protocol="modbus", source="m", asset="L1")
    assert t["klass"] == "other"
    assert t["canonical_alias"] == "site.l1.aux_relay"


# ── grouping + cross-protocol model ───────────────────────────────────────────

def _model():
    feeds = [
        {"protocol": "opcua", "source": "line1", "tags": [
            {"browse_name": "Temperature", "asset": "Line1", "class": "temperature",
             "unit": "degC", "node_id": "ns=2;i=1"},
            {"browse_name": "Pressure", "asset": "Line1", "class": "pressure",
             "unit": "bar", "node_id": "ns=2;i=2"},
        ]},
        {"protocol": "modbus", "source": "meter1", "asset": "Line1", "tags": [
            {"tag": "voltage_l1", "address": 0, "unit": "V"},
            {"tag": "temperature", "address": 6, "unit": "degC"},  # same qty as opcua
        ]},
        {"protocol": "modbus", "source": "meter2", "asset": "Line2", "tags": [
            {"tag": "fl", "address": 2},  # cryptic: short + class other
        ]},
    ]
    return am.cross_protocol_asset_model(feeds, site="plant")


@pytest.mark.unit
def test_groups_assets_across_protocols():
    model = _model()
    assert model["site"] == "plant"
    assert model["tag_count"] == 5
    assert set(model["protocols"]) == {"opcua", "modbus"}
    line1 = next(a for a in model["assets"] if a["asset"] == "Line1")
    # Line1 unites the OPC-UA folder AND the Modbus block.
    assert set(line1["protocols"]) == {"opcua", "modbus"}
    assert line1["tag_count"] == 4


@pytest.mark.unit
def test_cross_protocol_overlap_same_physical_quantity():
    model = _model()
    overlaps = model["naming_quality"]["cross_protocol_overlaps"]
    # temperature exposed on Line1 by BOTH opcua and modbus.
    hit = next(o for o in overlaps if o["asset"] == "Line1" and o["klass"] == "temperature")
    assert set(hit["protocols"]) == {"opcua", "modbus"}


@pytest.mark.unit
def test_alias_collision_detected_across_protocols():
    model = _model()
    collisions = model["naming_quality"]["alias_collisions"]
    # The two Line1 temperatures share the SAME class AND the same name
    # ("Temperature"/"temperature") → a GENUINE collision after disambiguation
    # (same physical point exposed by two protocols).
    hit = next(c for c in collisions if c["alias"] == "plant.line1.temperature_temperature")
    assert hit["count"] == 2
    assert set(hit["protocols"]) == {"opcua", "modbus"}
    assert model["naming_quality"]["verdict"] == "review"


@pytest.mark.unit
def test_same_class_different_name_siblings_get_unique_aliases():
    """Two temperatures with DIFFERENT names on one asset must NOT collide (the fix).

    Same-class siblings are normal in OT (zone A / zone B); the canonical alias
    must stay unique-per-tag (a usable rename map) and not spam the collision channel.
    """
    feeds = [{"protocol": "opcua", "source": "l", "asset": "Line1", "tags": [
        {"browse_name": "TempZoneA", "class": "temperature"},
        {"browse_name": "TempZoneB", "class": "temperature"},
    ]}]
    model = am.cross_protocol_asset_model(feeds, site="plant")
    aliases = sorted(t["canonical_alias"] for a in model["assets"] for t in a["tags"])
    assert aliases == ["plant.line1.temperature_tempzonea", "plant.line1.temperature_tempzoneb"]
    assert model["naming_quality"]["alias_collisions"] == []
    assert model["naming_quality"]["verdict"] == "clean"


@pytest.mark.unit
def test_case_insensitive_asset_fusion():
    """'Line1' (OPC-UA) and 'LINE1' (Modbus) are the same asset — they must fuse."""
    feeds = [
        {"protocol": "opcua", "source": "a", "asset": "Line1", "tags": [
            {"browse_name": "Temperature", "class": "temperature"}]},
        {"protocol": "modbus", "source": "b", "asset": "LINE1", "tags": [
            {"tag": "voltage_l1", "address": 0}]},
    ]
    model = am.cross_protocol_asset_model(feeds, site="p")
    assert model["asset_count"] == 1
    assert set(model["assets"][0]["protocols"]) == {"opcua", "modbus"}


@pytest.mark.unit
def test_cryptic_names_flagged():
    model = _model()
    assert "Line2/fl" in model["naming_quality"]["cryptic_names"] or \
        "fl" in str(model["naming_quality"]["cryptic_names"])


@pytest.mark.unit
def test_clean_model_has_clean_verdict():
    feeds = [
        {"protocol": "opcua", "source": "l1", "tags": [
            {"browse_name": "Temperature", "asset": "L1", "class": "temperature"},
        ]},
        {"protocol": "modbus", "source": "m1", "asset": "L1", "tags": [
            {"tag": "voltage_l1", "address": 0},
        ]},
    ]
    model = am.cross_protocol_asset_model(feeds, site="s")
    assert model["naming_quality"]["verdict"] == "clean"
    assert model["naming_quality"]["alias_collisions"] == []


@pytest.mark.unit
def test_empty_feeds_is_safe():
    model = am.cross_protocol_asset_model([], site="s")
    assert model["tag_count"] == 0
    assert model["asset_count"] == 0
    assert model["naming_quality"]["verdict"] == "clean"


@pytest.mark.unit
def test_invalid_feed_raises_teaching_error():
    with pytest.raises(ValueError, match="protocol"):
        am.cross_protocol_asset_model([{"source": "x", "tags": []}], site="s")
    with pytest.raises(ValueError, match="list of feed"):
        am.cross_protocol_asset_model({"not": "a list"}, site="s")
