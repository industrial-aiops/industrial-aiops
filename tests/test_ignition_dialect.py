"""Gateway read-layer dialect unit tests — the deployment abstraction.

Pure, socket-free: exercises the per-deployment field-alias normalizers directly.
The point of the connector is that two different Gateway HTTP web-API JSON shapes
(WebDev-module endpoints vs built-in status/system-function REST) fold into ONE
neutral schema across the whole read surface — these tests pin that folding down.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.ignition import dialects

# Raw deployment-shaped objects for the SAME logical data.
_WEBDEV_GATEWAY = {
    "gatewayName": "GW-A",
    "version": "8.1.30",
    "state": "RUNNING",
    "modules": [
        {"name": "OPC-UA", "state": "RUNNING", "version": "8.1.30"},
        {"name": "Tag Historian", "state": "RUNNING", "version": "8.1.30"},
    ],
}
_GATEWAY_GATEWAY = {
    "name": "GW-A",
    "version": "8.1.30",
    "state": "RUNNING",
    "moduleList": [
        {"moduleName": "OPC-UA", "moduleState": "RUNNING", "moduleVersion": "8.1.30"},
        {"moduleName": "Tag Historian", "moduleState": "RUNNING", "moduleVersion": "8.1.30"},
    ],
}

_WEBDEV_NODE = {
    "name": "OvenTemp",
    "fullPath": "Line1/OvenTemp",
    "tagType": "AtomicTag",
    "hasChildren": False,
}
_GATEWAY_NODE = {
    "name": "OvenTemp",
    "fullPath": "Line1/OvenTemp",
    "type": "AtomicTag",
    "hasChildren": False,
}

_WEBDEV_TAG = {"path": "Line1/OvenTemp", "value": 72.5, "quality": "Good", "timestamp": "t0"}
_GATEWAY_TAG = {
    "tagPath": "Line1/OvenTemp",
    "value": 72.5,
    "qualityCode": "Good",
    "timestamp": "t0",
}

_WEBDEV_ALARM = {
    "name": "HighTemp",
    "source": "Line1/OvenTemp",
    "priority": "High",
    "state": "ActiveUnacked",
    "label": "Oven over temperature",
    "timestamp": "t0",
}
_GATEWAY_ALARM = {
    "displayPath": "HighTemp",
    "source": "Line1/OvenTemp",
    "priority": "High",
    "state": "ActiveUnacked",
    "label": "Oven over temperature",
    "eventTime": "t0",
}

_WEBDEV_SAMPLE = {"timestamp": "t0", "value": 72.4, "quality": "Good"}
_GATEWAY_SAMPLE = {"timestamp": "t0", "value": 72.4, "qualityCode": "Good"}


@pytest.mark.unit
def test_gateway_status_normalizes_to_same_schema():
    dw = dialects.get_dialect("webdev")
    dg = dialects.get_dialect("gateway")
    w = dialects.normalize_gateway(_WEBDEV_GATEWAY, dw)
    g = dialects.normalize_gateway(_GATEWAY_GATEWAY, dg)
    assert set(w) == set(g) == {"name", "version", "state"}
    assert w == g == {"name": "GW-A", "version": "8.1.30", "state": "RUNNING"}


@pytest.mark.unit
def test_modules_extraction_differs_per_flavor():
    dw = dialects.get_dialect("webdev")
    dg = dialects.get_dialect("gateway")
    mw = [dialects.normalize_module(m, dw) for m in dw.modules(_WEBDEV_GATEWAY)]
    mg = [dialects.normalize_module(m, dg) for m in dg.modules(_GATEWAY_GATEWAY)]
    for out in (mw, mg):
        assert [m["name"] for m in out] == ["OPC-UA", "Tag Historian"]
        for m in out:
            assert set(m) == {"name", "state", "version"}
            assert m["state"] == "RUNNING" and m["version"] == "8.1.30"


@pytest.mark.unit
def test_browse_node_normalization_both_flavors():
    w = dialects.normalize_node(_WEBDEV_NODE, dialects.get_dialect("webdev"))
    g = dialects.normalize_node(_GATEWAY_NODE, dialects.get_dialect("gateway"))
    assert set(w) == set(g) == {"name", "path", "type", "has_children"}
    assert w == g
    assert w["path"] == "Line1/OvenTemp" and w["has_children"] is False


@pytest.mark.unit
def test_tag_value_normalization_both_flavors():
    w = dialects.normalize_tag(_WEBDEV_TAG, dialects.get_dialect("webdev"))
    g = dialects.normalize_tag(_GATEWAY_TAG, dialects.get_dialect("gateway"))
    assert set(w) == set(g) == {"path", "value", "quality", "timestamp"}
    assert w["value"] == g["value"] == 72.5
    assert w["path"] == g["path"] == "Line1/OvenTemp"
    assert w["quality"] == g["quality"] == "Good"


@pytest.mark.unit
def test_alarm_normalization_both_flavors():
    w = dialects.normalize_alarm(_WEBDEV_ALARM, dialects.get_dialect("webdev"))
    g = dialects.normalize_alarm(_GATEWAY_ALARM, dialects.get_dialect("gateway"))
    assert set(w) == set(g) == {"name", "source", "priority", "state", "label", "timestamp"}
    assert w["name"] == g["name"] == "HighTemp"
    assert w["timestamp"] == g["timestamp"] == "t0"
    assert w["label"] == g["label"] == "Oven over temperature"


@pytest.mark.unit
def test_sample_normalization_both_flavors():
    w = dialects.normalize_sample(_WEBDEV_SAMPLE, dialects.get_dialect("webdev"))
    g = dialects.normalize_sample(_GATEWAY_SAMPLE, dialects.get_dialect("gateway"))
    assert set(w) == set(g) == {"timestamp", "value", "quality"}
    assert w == g == {"timestamp": "t0", "value": 72.4, "quality": "Good"}


@pytest.mark.unit
def test_list_extraction_wrappers_differ_per_flavor():
    dw = dialects.get_dialect("webdev")
    dg = dialects.get_dialect("gateway")
    assert [n["name"] for n in dw.nodes({"tags": [{"name": "A"}, {"name": "B"}]})] == ["A", "B"]
    assert [n["name"] for n in dg.nodes({"results": [{"name": "A"}]})] == ["A"]
    # A non-collection body yields no items (never raises).
    assert dw.tags("nonsense") == []
    assert dg.alarms(None) == []


@pytest.mark.unit
def test_unknown_flavor_teaches():
    with pytest.raises(dialects.UnknownFlavorError, match="webdev, gateway"):
        dialects.get_dialect("proprietary-x")


@pytest.mark.unit
def test_dialects_are_frozen():
    d = dialects.get_dialect("webdev")
    with pytest.raises(Exception):
        d.name = "mutated"  # type: ignore[misc]
