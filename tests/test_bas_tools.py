"""BAS connector + tool tests — mock HTTP (no live device), governance, safety.

HTTP is mocked by monkeypatching the connector's documented patch points
(``client._http_get`` / ``client._http_put``), so these are true unit tests with
no sockets. They assert: the dialect folds Metasys vs Niagara wire shapes into
one schema over the full read surface; the size-cap / malformed-JSON / transport
teaching paths; and that ``bas_command`` refuses life-safety points, previews on
dry-run, and captures an undo of the prior value.
"""

from __future__ import annotations

import json

import pytest

from iaiops.connectors.bas import client as client_mod
from iaiops.connectors.bas import ops
from iaiops.core.runtime.session_factory import OTConnectionError

BASE = "https://bms"

# ── Vendor route tables: "METHOD /path" -> GET payload (dict) | PUT status (int).
_METASYS = {
    "GET /objects": {
        "items": [
            {"id": "p1", "itemReference": "NAE/AHU1.RAT", "name": "Return Air Temp"},
            {"id": "p2", "itemReference": "NAE/AHU1.SAT", "name": "Supply Air Temp"},
        ]
    },
    "GET /objects/p1": {
        "item": {
            "id": "p1",
            "itemReference": "NAE/AHU1.RAT",
            "presentValue": 21.5,
            "units": "degreesCelsius",
            "status": "normal",
        }
    },
    "GET /alarms": {
        "items": [
            {
                "id": "a1",
                "itemReference": "CH1.Fault",
                "priority": 40,
                "type": "highLimit",
                "message": "Chiller high limit",
                "creationTime": "2026-07-13T10:00:00Z",
            }
        ]
    },
    "GET /objects/p1/trendedAttributes/presentValue/samples": {
        "items": [
            {"timestamp": "2026-07-13T09:00:00Z", "value": 21.4},
            {"timestamp": "2026-07-13T09:05:00Z", "value": 21.6},
        ]
    },
    "PUT /objects/p1/attributes/presentValue": 200,
}
_NIAGARA = {
    "GET /obix/config/points/": {
        "children": [
            {
                "name": "RAT",
                "displayName": "Return Air Temp",
                "val": 21.5,
                "unit": "celsius",
                "status": "ok",
            },
            {
                "name": "SAT",
                "displayName": "Supply Air Temp",
                "val": 14.0,
                "unit": "celsius",
                "status": "ok",
            },
        ]
    },
    "GET /obix/RAT/": {
        "name": "RAT",
        "displayName": "Return Air Temp",
        "val": 21.5,
        "unit": "celsius",
        "status": "ok",
    },
    "GET /obix/alarms/": {
        "children": [
            {
                "href": "a1",
                "displayName": "Chiller high limit",
                "priority": "high",
                "alarmState": "unacked",
                "msgText": "Chiller high limit",
                "timestamp": "2026-07-13T10:00:00Z",
            }
        ]
    },
    "GET /obix/histories/RAT/": {
        "children": [
            {"timestamp": "2026-07-13T09:00:00Z", "value": 21.4},
            {"timestamp": "2026-07-13T09:05:00Z", "value": 21.6},
        ]
    },
    "PUT /obix/RAT/set/": 200,
}

_CAPTURED_HEADERS: list[dict] = []


@pytest.fixture
def routes(monkeypatch):
    """Install a fake HTTP layer; returns a setter for the active vendor's routes."""
    state: dict = {"table": {}}
    _CAPTURED_HEADERS.clear()

    def fake_get(url, headers, timeout, verify):
        _CAPTURED_HEADERS.append(dict(headers))
        key = f"GET {url[len(BASE) :]}"
        payload = state["table"][key]  # KeyError → surfaces as a translated failure
        return json.dumps(payload)

    def fake_put(url, payload, headers, timeout, verify):
        _CAPTURED_HEADERS.append(dict(headers))
        return int(state["table"][f"PUT {url[len(BASE) :]}"])

    monkeypatch.setattr(client_mod, "_http_get", fake_get)
    monkeypatch.setattr(client_mod, "_http_put", fake_put)

    def use(table: dict) -> None:
        state["table"] = table

    return use


# ─────────────────────────────────────────────────────────── read round-trips
@pytest.mark.unit
def test_point_list_both_vendors_same_schema(routes):
    routes(_METASYS)
    m = ops.point_list(BASE, "metasys")
    routes(_NIAGARA)
    n = ops.point_list(BASE, "niagara")
    assert m["point_count"] == n["point_count"] == 2
    for out in (m, n):
        for p in out["points"]:
            assert set(p) == {"id", "name", "value", "unit", "status"}
    assert m["points"][0]["id"] == "p1"
    assert n["points"][0]["id"] == "RAT" and n["points"][0]["value"] == 21.5


@pytest.mark.unit
def test_point_read_normalizes_present_value_both_vendors(routes):
    routes(_METASYS)
    m = ops.point_read(BASE, "metasys", ["p1"])
    routes(_NIAGARA)
    n = ops.point_read(BASE, "niagara", ["RAT"])
    assert m["points"][0]["value"] == n["points"][0]["value"] == 21.5
    assert m["points"][0]["name"] == "NAE/AHU1.RAT"
    assert n["points"][0]["name"] == "Return Air Temp"


@pytest.mark.unit
def test_point_read_no_ids_returns_error(routes):
    out = ops.point_read(BASE, "metasys", [])
    assert out["points"] == [] and "error" in out


@pytest.mark.unit
def test_alarm_list_both_vendors(routes):
    routes(_METASYS)
    m = ops.alarm_list(BASE, "metasys")
    routes(_NIAGARA)
    n = ops.alarm_list(BASE, "niagara")
    assert m["alarm_count"] == n["alarm_count"] == 1
    assert m["alarms"][0]["message"] == n["alarms"][0]["message"] == "Chiller high limit"
    assert m["alarms"][0]["id"] == n["alarms"][0]["id"] == "a1"


@pytest.mark.unit
def test_trend_read_is_bounded(routes):
    routes(_METASYS)
    out = ops.trend_read(BASE, "metasys", "p1", count=1)
    assert out["sample_count"] == 1  # count cap applied
    assert out["samples"][0] == {"timestamp": "2026-07-13T09:00:00Z", "value": 21.4}


# ─────────────────────────────────────────────────────────────── auth / secret
@pytest.mark.unit
def test_bearer_token_from_secret_store_is_sent(routes, monkeypatch):
    routes(_METASYS)
    monkeypatch.setattr(ops, "get_secret", lambda name: "tok-123")
    ops.point_list(BASE, "metasys", secret_name="bms-token")
    assert any(h.get("Authorization") == "Bearer tok-123" for h in _CAPTURED_HEADERS)


@pytest.mark.unit
def test_missing_named_secret_raises(monkeypatch):
    from iaiops.core.runtime.secretstore import SecretStoreError

    monkeypatch.setattr(
        ops, "get_secret", lambda name: (_ for _ in ()).throw(SecretStoreError("no such secret"))
    )
    with pytest.raises(ValueError, match="not found in the encrypted store"):
        ops.point_list(BASE, "metasys", secret_name="absent")


# ───────────────────────────────────────────────────────────── error teaching
@pytest.mark.unit
def test_response_size_cap_enforced():
    class _Resp:
        def iter_content(self, n):
            yield b"x" * (client_mod.MAX_RESPONSE_BYTES + 10)

    with pytest.raises(ValueError, match="size cap"):
        client_mod._read_capped(_Resp(), "https://bms/objects")


@pytest.mark.unit
def test_malformed_json_teaches():
    with pytest.raises(ValueError, match="unparseable JSON"):
        client_mod._parse_json("<html>not json", "https://bms/objects")


@pytest.mark.unit
def test_transport_failure_translated(monkeypatch):
    def dead(*a, **k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(client_mod, "_http_get", dead)
    with pytest.raises(OTConnectionError, match="BAS controller operation"):
        ops.point_list(BASE, "metasys")


@pytest.mark.unit
def test_unknown_vendor_translated():
    with pytest.raises(OTConnectionError, match="Unknown BAS vendor"):
        ops.point_list(BASE, "honeywell")


@pytest.mark.unit
def test_missing_base_url_teaches():
    with pytest.raises(OTConnectionError, match="no base_url"):
        ops.point_list("", "metasys")


# ────────────────────────────────────────────────────── command (guarded write)
@pytest.mark.unit
@pytest.mark.parametrize(
    "point_id, point_name",
    [("AHU/SmokeDamper-1", ""), ("bv9", "Stairwell Pressurization"), ("Fire_Relay", "")],
)
def test_command_refuses_life_safety_before_any_io(point_id, point_name, monkeypatch):
    # No HTTP layer installed: if the refusal did network I/O this would blow up
    # differently. It must raise the life-safety ValueError first.
    def boom(*a, **k):
        pytest.fail("network I/O happened before life-safety refusal")

    monkeypatch.setattr(client_mod, "_http_get", boom)
    monkeypatch.setattr(client_mod, "_http_put", boom)
    with pytest.raises(ValueError, match="life-safety denylist"):
        ops.command(BASE, "metasys", point_id, 1, point_name=point_name, dry_run=False)


@pytest.mark.unit
def test_command_dry_run_previews_and_captures_before(routes):
    routes(_METASYS)
    out = ops.command(BASE, "metasys", "p1", 22.0, dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == 21.5  # read-back of the prior value
    assert out["would_write"] == 22.0
    assert "applied" not in out


@pytest.mark.unit
def test_command_applied_writes_and_reports_before(routes):
    routes(_METASYS)
    out = ops.command(BASE, "metasys", "p1", 22.0, dry_run=False)
    assert out["dry_run"] is False
    assert out["before"] == 21.5
    assert out["written"] == 22.0
    assert out["applied"] is True


# ─────────────────────────────────────────────────────────────── governance
@pytest.mark.unit
def test_all_bas_tools_are_governed_with_right_risk():
    from mcp_server.tools import bas_tools

    reads = (
        bas_tools.bas_point_list,
        bas_tools.bas_point_read,
        bas_tools.bas_alarm_list,
        bas_tools.bas_trend_read,
    )
    for fn in reads:
        assert getattr(fn, "_is_governed_tool", False), f"{fn.__name__} not governed"
        assert getattr(fn, "_risk_level", "") == "low", f"{fn.__name__} must be low"
    assert getattr(bas_tools.bas_command, "_is_governed_tool", False)
    assert getattr(bas_tools.bas_command, "_risk_level", "") == "high"


@pytest.mark.unit
def test_undo_descriptor_restores_prior_value():
    from mcp_server.tools import bas_tools

    params = {"base_url": BASE, "vendor": "metasys", "point_id": "p1"}
    # No undo for a dry-run / unapplied result.
    assert bas_tools._bas_undo(params, {"dry_run": True, "before": 21.5}) is None
    # Undo for an applied write restores the captured BEFORE value.
    desc = bas_tools._bas_undo(params, {"applied": True, "before": 21.5, "written": 22.0})
    assert desc is not None
    assert desc["tool"] == "bas_command"
    assert desc["params"]["value"] == 21.5 and desc["params"]["dry_run"] is False
