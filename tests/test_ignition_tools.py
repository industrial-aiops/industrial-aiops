"""Gateway read-layer connector + tool tests — mock HTTP, governance, READ-ONLY.

HTTP is mocked by monkeypatching the connector's sole network primitive
(``client._http_get``), so these are true unit tests with no sockets. They
assert: the dialect folds WebDev vs Gateway wire shapes into one schema over the
full read surface (status/browse/read/alarm/history); the size-cap / malformed-
JSON / transport teaching paths; that the API token is drawn from the encrypted
secret store; and — the connector's defining invariant — that there is NO write
tool anywhere (all tools READ/low; no PUT/POST primitive; no command op).
"""

from __future__ import annotations

import json

import pytest

from iaiops.connectors.ignition import client as client_mod
from iaiops.connectors.ignition import ops
from iaiops.core.runtime.session_factory import OTConnectionError

BASE = "https://gw:8043"

# ── Flavor route tables: "GET /path" -> payload (dict). Encoded exactly as the
# client builds each URL (simple provider/paths chosen so no %-encoding differs).
_WEBDEV = {
    "GET /system/webdev/iaiops/status": {
        "gatewayName": "GW-A",
        "version": "8.1.30",
        "state": "RUNNING",
        "modules": [
            {"name": "OPC-UA", "state": "RUNNING", "version": "8.1.30"},
            {"name": "Tag Historian", "state": "RUNNING", "version": "8.1.30"},
        ],
    },
    "GET /system/webdev/iaiops/tags/browse?provider=default&path=": {
        "tags": [
            {
                "name": "OvenTemp",
                "fullPath": "OvenTemp",
                "tagType": "AtomicTag",
                "hasChildren": False,
            },  # noqa: E501
            {"name": "Line1", "fullPath": "Line1", "tagType": "Folder", "hasChildren": True},
        ]
    },
    "GET /system/webdev/iaiops/tags/read?provider=default&paths=OvenTemp": {
        "results": [{"path": "OvenTemp", "value": 72.5, "quality": "Good", "timestamp": "t0"}]
    },
    "GET /system/webdev/iaiops/alarms": {
        "alarms": [
            {
                "name": "HighTemp",
                "source": "OvenTemp",
                "priority": "High",
                "state": "ActiveUnacked",
                "label": "Oven over temperature",
                "timestamp": "t0",
            }
        ]
    },
    (
        "GET /system/webdev/iaiops/tags/history?provider=default"
        "&path=OvenTemp&start=t0&end=t1&count=100"
    ): {
        "rows": [
            {"timestamp": "t0", "value": 72.4, "quality": "Good"},
            {"timestamp": "t1", "value": 72.6, "quality": "Good"},
        ]
    },
}
_GATEWAY = {
    "GET /data/status/gateway": {
        "name": "GW-A",
        "version": "8.1.30",
        "state": "RUNNING",
        "moduleList": [
            {"moduleName": "OPC-UA", "moduleState": "RUNNING", "moduleVersion": "8.1.30"},
            {"moduleName": "Tag Historian", "moduleState": "RUNNING", "moduleVersion": "8.1.30"},
        ],
    },
    "GET /data/tags/browse/default/": {
        "results": [
            {"name": "OvenTemp", "fullPath": "OvenTemp", "type": "AtomicTag", "hasChildren": False},
            {"name": "Line1", "fullPath": "Line1", "type": "Folder", "hasChildren": True},
        ]
    },
    "GET /data/tags/read/default/OvenTemp": {
        "values": [{"tagPath": "OvenTemp", "value": 72.5, "qualityCode": "Good", "timestamp": "t0"}]
    },
    "GET /data/alarms/status": {
        "events": [
            {
                "displayPath": "HighTemp",
                "source": "OvenTemp",
                "priority": "High",
                "state": "ActiveUnacked",
                "label": "Oven over temperature",
                "eventTime": "t0",
            }
        ]
    },
    "GET /data/tags/history/default/OvenTemp?start=t0&end=t1&count=100": {
        "samples": [
            {"timestamp": "t0", "value": 72.4, "qualityCode": "Good"},
            {"timestamp": "t1", "value": 72.6, "qualityCode": "Good"},
        ]
    },
}

_CAPTURED_HEADERS: list[dict] = []


@pytest.fixture
def routes(monkeypatch):
    """Install a fake HTTP layer; returns a setter for the active flavor's routes."""
    state: dict = {"table": {}}
    _CAPTURED_HEADERS.clear()

    def fake_get(url, headers, timeout, verify):
        _CAPTURED_HEADERS.append(dict(headers))
        key = f"GET {url[len(BASE) :]}"
        payload = state["table"][key]  # KeyError → surfaces as a translated failure
        return json.dumps(payload)

    monkeypatch.setattr(client_mod, "_http_get", fake_get)

    def use(table: dict) -> None:
        state["table"] = table

    return use


# ─────────────────────────────────────────────────────────── read round-trips
@pytest.mark.unit
def test_gateway_status_both_flavors_same_schema(routes):
    routes(_WEBDEV)
    w = ops.gateway_status(BASE, "webdev")
    routes(_GATEWAY)
    g = ops.gateway_status(BASE, "gateway")
    for out in (w, g):
        assert out["reachable"] is True
        assert out["gateway"] == {"name": "GW-A", "version": "8.1.30", "state": "RUNNING"}
        assert out["module_count"] == 2
        assert out["modules"][0] == {"name": "OPC-UA", "state": "RUNNING", "version": "8.1.30"}


@pytest.mark.unit
def test_tag_browse_both_flavors(routes):
    routes(_WEBDEV)
    w = ops.tag_browse(BASE, "default", "", "webdev")
    routes(_GATEWAY)
    g = ops.tag_browse(BASE, "default", "", "gateway")
    assert w["node_count"] == g["node_count"] == 2
    for out in (w, g):
        for n in out["nodes"]:
            assert set(n) == {"name", "path", "type", "has_children"}
    assert w["nodes"][1]["has_children"] is True
    assert g["nodes"][0]["name"] == "OvenTemp"


@pytest.mark.unit
def test_tag_read_normalizes_value_both_flavors(routes):
    routes(_WEBDEV)
    w = ops.tag_read(BASE, "default", ["OvenTemp"], "webdev")
    routes(_GATEWAY)
    g = ops.tag_read(BASE, "default", ["OvenTemp"], "gateway")
    assert w["tags"][0]["value"] == g["tags"][0]["value"] == 72.5
    assert w["tags"][0]["quality"] == g["tags"][0]["quality"] == "Good"
    assert w["tags"][0]["path"] == g["tags"][0]["path"] == "OvenTemp"


@pytest.mark.unit
def test_tag_read_no_paths_returns_error(routes):
    out = ops.tag_read(BASE, "default", [])
    assert out["tags"] == [] and "error" in out


@pytest.mark.unit
def test_alarm_status_both_flavors(routes):
    routes(_WEBDEV)
    w = ops.alarm_status(BASE, "webdev")
    routes(_GATEWAY)
    g = ops.alarm_status(BASE, "gateway")
    assert w["alarm_count"] == g["alarm_count"] == 1
    assert w["alarms"][0]["name"] == g["alarms"][0]["name"] == "HighTemp"
    assert w["alarms"][0]["timestamp"] == g["alarms"][0]["timestamp"] == "t0"


@pytest.mark.unit
def test_tag_history_is_bounded_and_normalized(routes):
    routes(_WEBDEV)
    full = ops.tag_history(BASE, "default", "OvenTemp", "t0", "t1", count=100)
    assert full["sample_count"] == 2
    assert full["samples"][0] == {"timestamp": "t0", "value": 72.4, "quality": "Good"}


@pytest.mark.unit
def test_tag_history_count_cap_applied(routes):
    routes(_WEBDEV)
    # count=1 must clip the two-sample response server-side to one row.
    routes(
        {
            (
                "GET /system/webdev/iaiops/tags/history?provider=default"
                "&path=OvenTemp&start=t0&end=t1&count=1"
            ): {
                "rows": [
                    {"timestamp": "t0", "value": 72.4, "quality": "Good"},
                    {"timestamp": "t1", "value": 72.6, "quality": "Good"},
                ]
            }
        }
    )
    out = ops.tag_history(BASE, "default", "OvenTemp", "t0", "t1", count=1)
    assert out["sample_count"] == 1


# ─────────────────────────────────────────────────────────────── auth / secret
@pytest.mark.unit
def test_api_token_from_secret_store_is_sent(routes, monkeypatch):
    routes(_WEBDEV)
    monkeypatch.setattr(ops, "get_secret", lambda name: "tok-xyz")
    ops.gateway_status(BASE, "webdev", secret_name="gw-token")
    assert any(h.get("Authorization") == "Bearer tok-xyz" for h in _CAPTURED_HEADERS)


@pytest.mark.unit
def test_no_secret_name_sends_no_authorization(routes):
    routes(_WEBDEV)
    ops.gateway_status(BASE, "webdev")
    assert all("Authorization" not in h for h in _CAPTURED_HEADERS)


@pytest.mark.unit
def test_missing_named_secret_raises(monkeypatch):
    from iaiops.core.runtime.secretstore import SecretStoreError

    monkeypatch.setattr(
        ops, "get_secret", lambda name: (_ for _ in ()).throw(SecretStoreError("no such secret"))
    )
    with pytest.raises(ValueError, match="not found in the encrypted store"):
        ops.gateway_status(BASE, "webdev", secret_name="absent")


# ─────────────────────────────────────────────────── token-egress guard (SSRF)
def _no_io(monkeypatch):
    """Patch the HTTP primitive to fail loudly if any network I/O is attempted."""

    def boom(*a, **k):
        raise AssertionError("network I/O attempted — the egress guard must fire first")

    monkeypatch.setattr(client_mod, "_http_get", boom)


@pytest.mark.unit
def test_stored_token_egress_to_public_host_refused_before_io(monkeypatch):
    """A caller-supplied public base_url must NOT receive the stored API token."""
    monkeypatch.delenv("IAIOPS_TOKEN_EGRESS_HOSTS", raising=False)
    monkeypatch.setattr(ops, "get_secret", lambda name: "tok-xyz")
    _no_io(monkeypatch)
    with pytest.raises(OTConnectionError, match="IAIOPS_TOKEN_EGRESS_HOSTS"):
        ops.gateway_status("https://attacker.example.com", "webdev", secret_name="gw-token")


@pytest.mark.unit
def test_base_url_embedding_credentials_refused(monkeypatch):
    _no_io(monkeypatch)
    with pytest.raises(OTConnectionError, match="embeds credentials"):
        ops.gateway_status("https://tok@gw:8043", "webdev")


@pytest.mark.unit
def test_non_http_base_url_refused(monkeypatch):
    _no_io(monkeypatch)
    with pytest.raises(OTConnectionError, match="http"):
        ops.gateway_status("ftp://gw:8043", "webdev")


@pytest.mark.unit
def test_env_allowlisted_host_receives_token(monkeypatch):
    """The operator can opt a specific FQDN in via IAIOPS_TOKEN_EGRESS_HOSTS."""
    allowed_base = "https://gw.acme.example:8043"
    monkeypatch.setenv("IAIOPS_TOKEN_EGRESS_HOSTS", "*.acme.example")
    monkeypatch.setattr(ops, "get_secret", lambda name: "tok-xyz")
    _CAPTURED_HEADERS.clear()

    def fake_get(url, headers, timeout, verify):
        _CAPTURED_HEADERS.append(dict(headers))
        return json.dumps(_WEBDEV[f"GET {url[len(allowed_base) :]}"])

    monkeypatch.setattr(client_mod, "_http_get", fake_get)
    out = ops.gateway_status(allowed_base, "webdev", secret_name="gw-token")
    assert out["reachable"] is True
    assert any(h.get("Authorization") == "Bearer tok-xyz" for h in _CAPTURED_HEADERS)


# ───────────────────────────────────────────────────────────── error teaching
@pytest.mark.unit
def test_response_size_cap_enforced():
    class _Resp:
        def iter_content(self, n):
            yield b"x" * (client_mod.MAX_RESPONSE_BYTES + 10)

    with pytest.raises(ValueError, match="size cap"):
        client_mod._read_capped(_Resp(), "https://gw/status")


@pytest.mark.unit
def test_malformed_json_teaches():
    with pytest.raises(ValueError, match="unparseable JSON"):
        client_mod._parse_json("<html>not json", "https://gw/status")


@pytest.mark.unit
def test_transport_failure_translated(monkeypatch):
    def dead(*a, **k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(client_mod, "_http_get", dead)
    with pytest.raises(OTConnectionError, match="Gateway read"):
        ops.gateway_status(BASE, "webdev")


@pytest.mark.unit
def test_unknown_flavor_translated():
    with pytest.raises(OTConnectionError, match="Unknown Gateway API flavor"):
        ops.gateway_status(BASE, "proprietary-x")


@pytest.mark.unit
def test_missing_base_url_teaches():
    with pytest.raises(OTConnectionError, match="no base_url"):
        ops.gateway_status("", "webdev")


# ─────────────────────────────────────────────────────────────── governance
@pytest.mark.unit
def test_all_ignition_tools_are_governed_read_low():
    from mcp_server.tools import ignition_tools

    tools = (
        ignition_tools.ignition_gateway_status,
        ignition_tools.ignition_tag_browse,
        ignition_tools.ignition_tag_read,
        ignition_tools.ignition_alarm_status,
        ignition_tools.ignition_tag_history,
    )
    for fn in tools:
        assert getattr(fn, "_is_governed_tool", False), f"{fn.__name__} not governed"
        assert getattr(fn, "_risk_level", "") == "low", f"{fn.__name__} must be low"


@pytest.mark.unit
def test_connector_has_no_write_surface():
    """The defining invariant: NO write path anywhere in this connector."""
    import inspect

    from mcp_server.tools import ignition_tools

    # No high-risk tool registered in the module source.
    src = inspect.getsource(ignition_tools)
    assert 'risk_level="high"' not in src and 'risk_level="medium"' not in src
    # No write/command op is exported, and the client exposes no PUT/POST primitive.
    for banned in ("command", "write", "tag_write", "put"):
        assert not hasattr(ops, banned), f"ops unexpectedly exports {banned!r}"
    assert not hasattr(client_mod, "_http_put")
    assert not hasattr(client_mod, "_http_post")
