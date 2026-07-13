"""BAS dialect unit tests — the vendor abstraction (Metasys vs Niagara shapes).

Pure, socket-free: exercises the per-vendor field-alias normalizers and the
life-safety denylist directly. The point of the connector is that two very
different controller JSON shapes fold into ONE neutral schema — these tests pin
that folding down.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.bas import dialects

# Raw vendor-shaped objects for the SAME logical point (return-air temperature).
_METASYS_POINT = {
    "item": {
        "id": "p1",
        "itemReference": "NAE55/AHU1.RAT",
        "presentValue": 21.5,
        "units": "degreesCelsius",
        "status": "normal",
    }
}
_NIAGARA_POINT = {
    "name": "RAT",
    "displayName": "Return Air Temp",
    "val": 21.5,
    "unit": "celsius",
    "status": "ok",
}


@pytest.mark.unit
def test_metasys_and_niagara_points_normalize_to_same_schema():
    m = dialects.normalize_point(_METASYS_POINT, dialects.get_dialect("metasys"))
    n = dialects.normalize_point(_NIAGARA_POINT, dialects.get_dialect("niagara"))
    # Identical KEY set across vendors — the neutral schema.
    assert set(m) == set(n) == {"id", "name", "value", "unit", "status"}
    # Both surface the same present value despite different field names / nesting.
    assert m["value"] == n["value"] == 21.5
    assert m["id"] == "p1" and n["id"] == "RAT"
    assert m["name"] == "NAE55/AHU1.RAT" and n["name"] == "Return Air Temp"


@pytest.mark.unit
def test_metasys_value_container_is_unwrapped():
    """Metasys nests attributes under 'item'; the dialect must descend into it."""
    d = dialects.get_dialect("metasys")
    assert d.value_container == "item"
    assert dialects.normalize_point(_METASYS_POINT, d)["value"] == 21.5


@pytest.mark.unit
def test_list_key_extraction_differs_per_vendor():
    metasys = dialects.get_dialect("metasys")
    niagara = dialects.get_dialect("niagara")
    m_items = metasys.items({"items": [{"id": "p1"}, {"id": "p2"}]})
    n_items = niagara.items({"children": [{"name": "RAT"}]})
    assert [o["id"] for o in m_items] == ["p1", "p2"]
    assert [o["name"] for o in n_items] == ["RAT"]
    # A bare list (no wrapper key) is also accepted.
    assert niagara.items([{"name": "X"}]) == [{"name": "X"}]
    # A non-collection body yields no items (never raises).
    assert metasys.items("nonsense") == []


@pytest.mark.unit
def test_alarm_normalization_both_vendors():
    m = dialects.normalize_alarm(
        {
            "id": "a1",
            "itemReference": "CH1.Fault",
            "priority": 40,
            "type": "highLimit",
            "message": "Chiller high limit",
            "creationTime": "2026-07-13T10:00:00Z",
        },
        dialects.get_dialect("metasys"),
    )
    n = dialects.normalize_alarm(
        {
            "href": "a1",
            "displayName": "Chiller high limit",
            "priority": "high",
            "alarmState": "unacked",
            "msgText": "Chiller high limit",
            "timestamp": "2026-07-13T10:00:00Z",
        },
        dialects.get_dialect("niagara"),
    )
    assert set(m) == set(n) == {"id", "name", "priority", "state", "message", "timestamp"}
    assert m["id"] == n["id"] == "a1"
    assert m["message"] == n["message"] == "Chiller high limit"
    assert m["state"] == "highLimit" and n["state"] == "unacked"


@pytest.mark.unit
def test_sample_normalization_both_vendors():
    d_m = dialects.get_dialect("metasys")
    d_n = dialects.get_dialect("niagara")
    m = dialects.normalize_sample({"timestamp": "t0", "value": 21.4}, d_m)
    n = dialects.normalize_sample({"timestamp": "t0", "val": 21.4}, d_n)
    assert m == n == {"timestamp": "t0", "value": 21.4}


@pytest.mark.unit
def test_unknown_vendor_teaches():
    with pytest.raises(dialects.UnknownVendorError, match="metasys, niagara"):
        dialects.get_dialect("honeywell-ebi")


@pytest.mark.unit
@pytest.mark.parametrize(
    "point_id, point_name",
    [
        ("AHU1/SmokeDamper-3", ""),
        ("bv-201", "Stairwell Pressurization Setpoint"),
        ("FireAlarmRelay", ""),
        ("egress-door-lock", ""),
        ("SPRINKLER_FlowSw", ""),
        ("", "Smoke Exhaust Fan"),
    ],
)
def test_life_safety_points_are_flagged(point_id, point_name):
    assert dialects.is_life_safety(point_id, point_name), (
        f"{point_id!r}/{point_name!r} should hit the life-safety denylist"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "point_id, point_name",
    [
        ("AHU1.RAT", "Return Air Temp"),
        ("VAV-3-14", "Zone Cooling Setpoint"),
        ("CH1.ChwSetpoint", ""),
    ],
)
def test_normal_points_are_not_flagged(point_id, point_name):
    assert dialects.is_life_safety(point_id, point_name) == ""


@pytest.mark.unit
def test_dialects_are_frozen():
    d = dialects.get_dialect("metasys")
    with pytest.raises(Exception):
        d.name = "mutated"  # type: ignore[misc]
