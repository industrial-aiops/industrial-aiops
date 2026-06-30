"""Adopted alias-map persistence + cross-run diff (pure logic + bounded file I/O).

The asset model PROPOSES canonical aliases; this layer lets an operator ADOPT a
map, persist it under the iaiops config dir, and DIFF a later discovery run
against the stored baseline (added / removed / renamed / reclassified). All file
I/O is steered to a tmp dir — these tests never touch the real ``~/.iaiops``.
"""

from __future__ import annotations

import json
import stat

import pytest

from iaiops.core.brain import alias_store as als
from iaiops.core.brain import asset_model as am

# ── extraction from an asset-model run ─────────────────────────────────────────

def _model():
    feeds = [
        {"protocol": "opcua", "source": "line1", "tags": [
            {"browse_name": "Temperature", "asset": "Line1", "class": "temperature",
             "node_id": "ns=2;i=1"},
            {"browse_name": "Pressure", "asset": "Line1", "class": "pressure",
             "node_id": "ns=2;i=2"},
        ]},
        {"protocol": "modbus", "source": "meter1", "asset": "Line1", "tags": [
            {"tag": "voltage_l1", "address": 0},
        ]},
    ]
    return am.cross_protocol_asset_model(feeds, site="plant")


@pytest.mark.unit
def test_extract_alias_map_keys_on_canonical_alias():
    amap = als.extract_alias_map(_model())
    assert set(amap) == {
        "plant.line1.temperature", "plant.line1.pressure", "plant.line1.voltage",
    }
    entry = amap["plant.line1.temperature"]
    assert entry["ref"] == "ns=2;i=1"
    assert entry["protocol"] == "opcua"
    assert entry["asset"] == "Line1"
    assert entry["name"] == "Temperature"
    assert entry["class"] == "temperature"


@pytest.mark.unit
def test_extract_does_not_mutate_model():
    model = _model()
    before = json.dumps(model, sort_keys=True, default=str)
    als.extract_alias_map(model)
    assert json.dumps(model, sort_keys=True, default=str) == before


@pytest.mark.unit
def test_extract_rejects_non_model():
    with pytest.raises(ValueError, match="asset model"):
        als.extract_alias_map({"not": "a model"})


# ── persistence (save / load round-trip) ───────────────────────────────────────

@pytest.mark.unit
def test_save_then_load_round_trips(tmp_path):
    amap = als.extract_alias_map(_model())
    path = als.save_alias_map("plant", amap, base_dir=tmp_path)
    assert path.exists()
    loaded = als.load_alias_map("plant", base_dir=tmp_path)
    assert loaded == amap


@pytest.mark.unit
def test_save_uses_owner_only_permissions(tmp_path):
    path = als.save_alias_map("plant", {"a.b.c": {"ref": "1"}}, base_dir=tmp_path)
    file_mode = stat.S_IMODE(path.stat().st_mode)
    dir_mode = stat.S_IMODE(path.parent.stat().st_mode)
    assert file_mode == 0o600
    assert dir_mode == 0o700


@pytest.mark.unit
def test_save_is_deterministic_for_same_map(tmp_path):
    amap = {"p.l.temperature": {"ref": "ns=2;i=1", "protocol": "opcua",
                                "asset": "L", "name": "Temperature", "class": "temperature"}}
    p1 = als.save_alias_map("s1", amap, base_dir=tmp_path)
    body1 = p1.read_text("utf-8")
    body2 = als.save_alias_map("s1", amap, base_dir=tmp_path).read_text("utf-8")
    # the persisted alias block is stable across writes (no time/order churn)
    assert json.loads(body1)["aliases"] == json.loads(body2)["aliases"]


@pytest.mark.unit
def test_load_missing_site_teaches(tmp_path):
    with pytest.raises(FileNotFoundError, match="No adopted alias map"):
        als.load_alias_map("ghost", base_dir=tmp_path)


@pytest.mark.unit
def test_load_corrupt_json_teaches(tmp_path):
    bad = als._site_path("broken", tmp_path)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ not json", "utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        als.load_alias_map("broken", base_dir=tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize("bad_site", ["", "   ", "..", "../escape", "a/b"])
def test_save_rejects_unsafe_site(tmp_path, bad_site):
    with pytest.raises(ValueError, match="site"):
        als.save_alias_map(bad_site, {"a.b": {"ref": "1"}}, base_dir=tmp_path)


@pytest.mark.unit
def test_save_rejects_non_dict_map(tmp_path):
    with pytest.raises(ValueError, match="alias map"):
        als.save_alias_map("plant", ["not", "a", "dict"], base_dir=tmp_path)


@pytest.mark.unit
def test_list_sites(tmp_path):
    als.save_alias_map("plant", {"a.b": {"ref": "1"}}, base_dir=tmp_path)
    als.save_alias_map("annex", {"c.d": {"ref": "2"}}, base_dir=tmp_path)
    assert als.list_sites(base_dir=tmp_path) == ["annex", "plant"]
    assert als.list_sites(base_dir=tmp_path / "nope") == []


# ── diff ───────────────────────────────────────────────────────────────────────

def _entry(ref, alias_class, name="N", proto="opcua", asset="L"):
    return {"ref": ref, "protocol": proto, "asset": asset, "name": name,
            "class": alias_class}


@pytest.mark.unit
def test_diff_identical_is_stable():
    amap = als.extract_alias_map(_model())
    diff = als.diff_alias_map(amap, amap)
    assert diff["verdict"] == "stable"
    assert diff["counts"] == {"added": 0, "removed": 0, "renamed": 0, "reclassified": 0}


@pytest.mark.unit
def test_diff_added_and_removed():
    prev = {"s.l.temperature": _entry("ns=2;i=1", "temperature")}
    curr = {"s.l.pressure": _entry("ns=2;i=9", "pressure")}
    diff = als.diff_alias_map(prev, curr)
    assert [a["alias"] for a in diff["added"]] == ["s.l.pressure"]
    assert [r["alias"] for r in diff["removed"]] == ["s.l.temperature"]
    assert diff["verdict"] == "changed"


@pytest.mark.unit
def test_diff_renamed_same_ref_new_alias():
    prev = {"s.l.temp": _entry("ns=2;i=1", "temperature")}
    curr = {"s.l.temperature": _entry("ns=2;i=1", "temperature")}
    diff = als.diff_alias_map(prev, curr)
    assert diff["added"] == [] and diff["removed"] == []
    assert diff["renamed"] == [
        {"protocol": "opcua", "ref": "ns=2;i=1", "from": "s.l.temp", "to": "s.l.temperature"}
    ]
    assert diff["verdict"] == "changed"


@pytest.mark.unit
def test_diff_reclassified_same_ref_and_alias_new_class():
    prev = {"s.l.flow": _entry("ns=2;i=3", "other")}
    curr = {"s.l.flow": _entry("ns=2;i=3", "flow")}
    diff = als.diff_alias_map(prev, curr)
    assert diff["renamed"] == []
    assert diff["reclassified"] == [
        {"alias": "s.l.flow", "protocol": "opcua", "ref": "ns=2;i=3",
         "from": "other", "to": "flow"}
    ]
    assert diff["verdict"] == "changed"


@pytest.mark.unit
def test_diff_does_not_mutate_inputs():
    prev = {"s.l.temp": _entry("ns=2;i=1", "temperature")}
    curr = {"s.l.temperature": _entry("ns=2;i=1", "temperature")}
    pbefore = json.dumps(prev, sort_keys=True)
    cbefore = json.dumps(curr, sort_keys=True)
    als.diff_alias_map(prev, curr)
    assert json.dumps(prev, sort_keys=True) == pbefore
    assert json.dumps(curr, sort_keys=True) == cbefore


@pytest.mark.unit
def test_diff_validates_inputs():
    with pytest.raises(ValueError, match="alias map"):
        als.diff_alias_map(["x"], {})
    with pytest.raises(ValueError, match="alias map"):
        als.diff_alias_map({}, "nope")


@pytest.mark.unit
def test_diff_no_ref_falls_back_to_alias_identity():
    # tags without a ref can't be tracked by ref → an alias change reads as add+remove.
    prev = {"s.l.a": _entry("", "other")}
    curr = {"s.l.b": _entry("", "other")}
    diff = als.diff_alias_map(prev, curr)
    assert [a["alias"] for a in diff["added"]] == ["s.l.b"]
    assert [r["alias"] for r in diff["removed"]] == ["s.l.a"]
    assert diff["renamed"] == []
