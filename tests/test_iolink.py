"""IO-Link connector tests against an in-process mock master (both JSON flavors).

A real ``http.server`` thread plays the IO-Link master: it answers the ifm
IoT-Core POST envelope on ``/`` AND plain-REST GETs of the same datapoint paths,
so the client, ops, bounds, size-cap, and error paths are exercised over real
HTTP — the self-test story for a connector whose live-master paths are 待核实.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from iaiops.connectors.iolink import ops
from iaiops.connectors.iolink.client import MAX_RESPONSE_BYTES, IoLinkClient
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import OTConnectionError, iolink_session

# The mock master's datapoint tree: port 1 carries a device, port 2 is IO-Link
# mode but empty, ports >= 3 don't exist on this master.
_DATAPOINTS = {
    "/deviceinfo/productcode/getdata": "AL1352",
    "/deviceinfo/serialnumber/getdata": "000201234567",
    "/deviceinfo/hwrevision/getdata": "AA",
    "/deviceinfo/swrevision/getdata": "3.1.29",
    "/iolinkmaster/port[1]/mode/getdata": 3,
    "/iolinkmaster/port[1]/iolinkdevice/status/getdata": 2,
    "/iolinkmaster/port[1]/iolinkdevice/vendorid/getdata": 310,
    "/iolinkmaster/port[1]/iolinkdevice/deviceid/getdata": 967,
    "/iolinkmaster/port[1]/iolinkdevice/productname/getdata": "VVB001",
    "/iolinkmaster/port[1]/iolinkdevice/serial/getdata": "SN-0042",
    "/iolinkmaster/port[1]/iolinkdevice/pdin/getdata": "03C9",
    "/iolinkmaster/port[2]/mode/getdata": 3,
}
_ISDU = {(1, 16, 0): "0F2A", (1, 64, 1): "01"}


class _MockMaster(BaseHTTPRequestHandler):
    """Serves both flavors; records request methods for flavor-switch assertions."""

    methods_seen: list[str] = []

    def log_message(self, *args) -> None:  # noqa: D102 — silence test output
        pass

    def _reply(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _lookup(self, adr: str, args: dict):
        if adr.endswith("/iolreadacyclic"):
            port = int(adr.split("port[")[1].split("]")[0])
            key = (port, int(args.get("index", -1)), int(args.get("subindex", 0)))
            if key in _ISDU:
                return {"cid": 1, "code": 200, "data": {"value": _ISDU[key]}}
            return {"cid": 1, "code": 530, "error": "isdu error"}
        if adr == "/huge":  # size-cap fixture: > MAX_RESPONSE_BYTES of JSON
            return {"cid": 1, "code": 200, "data": {"value": "x" * (MAX_RESPONSE_BYTES + 100)}}
        if adr == "/garbage":
            return None  # sentinel: caller writes raw non-JSON
        if adr in _DATAPOINTS:
            return {"cid": 1, "code": 200, "data": {"value": _DATAPOINTS[adr]}}
        return {"cid": 1, "code": 503, "error": "not found"}

    def do_POST(self) -> None:  # ifm IoT-Core envelope flavor
        type(self).methods_seen.append("POST")
        length = int(self.headers.get("Content-Length", 0))
        try:
            envelope = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._reply(200, {"cid": -1, "code": 400})
            return
        adr = "/" + str(envelope.get("adr", "")).strip("/")
        payload = self._lookup(adr, envelope.get("data") or {})
        if payload is None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>not json at all")
            return
        self._reply(200, payload)

    def do_GET(self) -> None:  # plain-REST flavor
        type(self).methods_seen.append("GET")
        parsed = urlparse(self.path)
        args = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        # requests percent-encodes the datapoint brackets (port[1] → port%5B1%5D).
        payload = self._lookup(unquote(parsed.path), args)
        if payload is None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>not json at all")
            return
        self._reply(200, payload)


@pytest.fixture(scope="module")
def mock_master():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMaster)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


def _target(base_url: str, flavor: str = "") -> TargetConfig:
    return TargetConfig(
        name="master1", protocol="iolink", agent_url=base_url, flavor=flavor, timeout_s=5.0
    )


# ---------------------------------------------------------------- round-trips


@pytest.mark.integration
@pytest.mark.parametrize("flavor", ["iotcore", "rest"])
def test_master_info_round_trip_both_flavors(mock_master, flavor):
    out = ops.master_info(_target(mock_master, flavor))
    assert out["flavor"] == flavor
    assert out["master"]["productcode"] == "AL1352"
    assert out["master"]["serialnumber"] == "000201234567"
    assert "unavailable" not in out


@pytest.mark.integration
def test_ports_sweep_is_bounded_and_classifies(mock_master):
    out = ops.ports(_target(mock_master), count=4)
    assert out["ports_checked"] == 4
    by_port = {p["port"]: p for p in out["ports"]}
    assert by_port[1]["device_connected"] is True
    assert by_port[1]["productname"] == "VVB001"
    assert by_port[1]["vendorid"] == 310
    assert by_port[2]["present"] is True and by_port[2]["device_connected"] is False
    assert by_port[3]["present"] is False and "error" in by_port[3]
    assert out["devices_connected"] == 1 and out["ports_present"] == 2


@pytest.mark.integration
def test_ports_count_capped_at_max(mock_master):
    out = ops.ports(_target(mock_master), count=999)
    assert out["ports_checked"] == ops.MAX_PORTS == 32


@pytest.mark.integration
def test_device_info_round_trip(mock_master):
    out = ops.device_info(_target(mock_master), port=1)
    dev = out["device"]
    assert dev == {
        "vendorid": 310,
        "deviceid": 967,
        "productname": "VVB001",
        "serial": "SN-0042",
        "status": 2,
    }


@pytest.mark.integration
def test_read_pdin_hex_and_bytes(mock_master):
    out = ops.read_pdin(_target(mock_master), port=1)
    assert out["pdin_hex"] == "03C9"
    assert out["bytes"] == [0x03, 0xC9] and out["byte_count"] == 2


@pytest.mark.integration
@pytest.mark.parametrize("flavor", ["iotcore", "rest"])
def test_read_isdu_round_trip_both_flavors(mock_master, flavor):
    out = ops.read_isdu(_target(mock_master, flavor), port=1, index=16)
    assert out["value"] == "0F2A" and out["subindex"] == 0
    out = ops.read_isdu(_target(mock_master, flavor), port=1, index=64, subindex=1)
    assert out["value"] == "01"


@pytest.mark.integration
def test_scan_one_shot(mock_master):
    out = ops.scan(_target(mock_master), count=3)
    assert out["master"]["productcode"] == "AL1352"
    assert out["ports_checked"] == 3 and out["devices_connected"] == 1


# ------------------------------------------------------------------- bounds


@pytest.mark.unit
@pytest.mark.parametrize("port", [0, 33, -1])
def test_port_out_of_range_rejected(port):
    with pytest.raises(ValueError, match="port must be 1"):
        ops.read_pdin(_target("http://unused"), port=port)


@pytest.mark.unit
def test_isdu_index_and_subindex_bounds():
    with pytest.raises(ValueError, match="index must be"):
        ops.read_isdu(_target("http://unused"), port=1, index=70000)
    with pytest.raises(ValueError, match="subindex must be"):
        ops.read_isdu(_target("http://unused"), port=1, index=16, subindex=300)


# -------------------------------------------------------------- error paths


@pytest.mark.integration
def test_response_size_cap_enforced(mock_master):
    client = IoLinkClient(base_url=mock_master, flavor="rest", timeout_s=5.0)
    with pytest.raises(ValueError, match="size cap"):
        client.request("/huge")


@pytest.mark.integration
def test_malformed_json_teaches(mock_master):
    client = IoLinkClient(base_url=mock_master, flavor="rest", timeout_s=5.0)
    with pytest.raises(ValueError, match="unparseable JSON"):
        client.request("/garbage")


@pytest.mark.integration
def test_iotcore_error_code_surfaces(mock_master):
    client = IoLinkClient(base_url=mock_master, timeout_s=5.0)
    with pytest.raises(ValueError, match="code 503"):
        client.request("/iolinkmaster/port[9]/mode/getdata")


@pytest.mark.integration
def test_session_translates_transport_failures(mock_master):
    # A dead master → teaching OTConnectionError, not a raw requests exception.
    target = _target("http://127.0.0.1:1")  # nothing listens on port 1
    with pytest.raises(OTConnectionError, match="IO-Link operation on 'master1'"):
        ops.master_info(target)


@pytest.mark.unit
def test_session_guards_protocol():
    other = TargetConfig(name="plc", protocol="modbus", host="h")
    with pytest.raises(OTConnectionError, match="not iolink"):
        with iolink_session(other):
            pass


@pytest.mark.unit
def test_unknown_flavor_rejected():
    target = _target("http://unused", flavor="soap")
    with pytest.raises(OTConnectionError, match="iotcore.*rest|rest.*iotcore"):
        with iolink_session(target):
            pass


@pytest.mark.integration
def test_non_hex_pdin_teaches(mock_master, monkeypatch):
    from iaiops.connectors.iolink import client as client_mod

    adr = "/iolinkmaster/port[1]/iolinkdevice/pdin/getdata"
    monkeypatch.setitem(_DATAPOINTS, adr, "zz-not-hex")
    try:
        with pytest.raises(ValueError, match="not a hex string"):
            ops.read_pdin(_target(mock_master), port=1)
    finally:
        _DATAPOINTS[adr] = "03C9"
    assert client_mod  # keep the import used


# ------------------------------------------------------- flavor + governance


@pytest.mark.integration
def test_flavor_switching_uses_right_http_method(mock_master):
    _MockMaster.methods_seen.clear()
    ops.master_info(_target(mock_master, "iotcore"))
    assert set(_MockMaster.methods_seen) == {"POST"}
    _MockMaster.methods_seen.clear()
    ops.master_info(_target(mock_master, "rest"))
    assert set(_MockMaster.methods_seen) == {"GET"}


@pytest.mark.unit
def test_blank_flavor_defaults_to_iotcore():
    from iaiops.connectors.iolink.transport import _build_iolink_client

    client = _build_iolink_client(_target("http://h"))
    assert client.flavor == "iotcore" and client.timeout_s == 5.0


@pytest.mark.unit
def test_all_iolink_tools_are_governed_read_only():
    from mcp_server.tools import iolink_tools

    tools = (
        iolink_tools.iolink_master_info,
        iolink_tools.iolink_ports,
        iolink_tools.iolink_device_info,
        iolink_tools.iolink_read_pdin,
        iolink_tools.iolink_read_isdu,
        iolink_tools.iolink_scan,
    )
    assert len(tools) == 6
    for fn in tools:
        assert getattr(fn, "_is_governed_tool", False), f"{fn.__name__} not governed"
        assert getattr(fn, "_risk_level", "") == "low", f"{fn.__name__} must be low risk"
    # Read-only v1: the module must expose no write/set tool at all.
    names = [n for n in dir(iolink_tools) if n.startswith("iolink_")]
    assert not [n for n in names if "write" in n or "set" in n]
