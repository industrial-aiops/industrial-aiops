"""Phoenix Contact PLCnext vPLC (虚拟化 PLC) route verification.

PLCnext Technology exposes its process data over two standard interfaces that
this project already speaks: a built-in **OPC-UA server** (opc.tcp 4840) and a
**Modbus-TCP server** (user-mapped registers). Rather than add a new connector,
the "vPLC route verification" (HLD §8.2 / §10 P6) proves the existing OPC-UA and
Modbus connectors reach a PLCnext-shaped target:

* OPC-UA route — a REAL in-process ``asyncua`` server reproduces a PLCnext GDS /
  ``Arp.Plc.Eclr`` address space; the connector browses/reads it over opc.tcp.
* Modbus route — the pymodbus client is faked (same seam as ``test_modbus``) to
  present a PLCnext process-data holding-register block; the connector decodes it.

Live-hardware reads against a physical/virtual PLCnext are still 待核实 (no gear
in CI); this pins the wire route + decode, mirroring the energy/building passes.
"""

from __future__ import annotations

import socket
import struct

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.modbus import ops as modbus_ops
from iaiops.connectors.opcua import discovery as opcua_discovery
from iaiops.connectors.opcua import ops as opcua_ops
from iaiops.core.brain.overview import protocols_supported
from iaiops.core.runtime.config import TargetConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- #
# OPC-UA route — real in-process server shaped like a PLCnext address space
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def plcnext_opcua():
    """Start a real OPC-UA server mimicking a PLCnext GDS/PLC address space."""
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/plcnext"
    srv = Server()
    srv.set_endpoint(url)
    srv.set_server_name("PLCnext-vPLC-sim")
    idx = srv.register_namespace("urn:phoenixcontact:plcnext")
    objects = srv.nodes.objects
    # PLCnext surfaces GDS ports under the Arp.Plc.Eclr root.
    eclr = objects.add_folder(idx, "Arp.Plc.Eclr")
    prog = eclr.add_folder(idx, "MainInstance")
    cycle = prog.add_variable(idx, "Cycletime_ms", 1.0)
    di1 = prog.add_variable(idx, "DI1", True)
    temp = prog.add_variable(idx, "Tank_Temperature", 72.5)
    srv.start()
    try:
        yield {
            "url": url,
            "cycle": cycle.nodeid.to_string(),
            "di1": di1.nodeid.to_string(),
            "temp": temp.nodeid.to_string(),
        }
    finally:
        srv.stop()


def _opcua_target(url: str) -> TargetConfig:
    return TargetConfig(name="plcnext", protocol="opcua", endpoint_url=url)


@pytest.mark.integration
def test_plcnext_opcua_route_reachable(plcnext_opcua):
    """The OPC-UA connector connects to the PLCnext server and reports it up."""
    info = opcua_ops.server_info(_opcua_target(plcnext_opcua["url"]))
    assert info["state"] == 0
    assert any("phoenixcontact" in n for n in info["namespaces"])


@pytest.mark.integration
def test_plcnext_opcua_route_discovers_gds_tags(plcnext_opcua):
    """Tag discovery walks the Arp.Plc.Eclr tree and finds the mapped variables."""
    tags = opcua_discovery.discover_tags(
        _opcua_target(plcnext_opcua["url"]), max_depth=6, include_standard=False
    )
    names = {t["browse_name"] for t in tags}
    assert {"Cycletime_ms", "DI1", "Tank_Temperature"} <= names


@pytest.mark.integration
def test_plcnext_opcua_route_reads_value(plcnext_opcua):
    """A single mapped GDS variable reads back its value over the route."""
    r = opcua_ops.read_node(_opcua_target(plcnext_opcua["url"]), plcnext_opcua["temp"])
    assert r["value"] == 72.5


# --------------------------------------------------------------------------- #
# Modbus route — faked PLCnext Modbus-TCP process-data block
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, registers=None, error=False):
        self.registers = registers or []
        self._error = error

    def isError(self):  # noqa: N802 — mirrors pymodbus's response API
        return self._error


class _FakePlcnextModbusClient:
    """pymodbus double for a PLCnext Modbus-TCP server (read-only holding block)."""

    def __init__(self, registers):
        self._registers = registers

    def connect(self):
        return True

    def close(self):
        return None

    def read_holding_registers(self, address, *, count=1, device_id=1, no_response_expected=False):
        return _FakeResp(registers=self._registers[address : address + count])


@pytest.fixture
def plcnext_modbus(monkeypatch):
    # PLCnext maps a float32 process value (25.0, big-endian) into 40001..40002.
    hi, lo = struct.unpack(">HH", struct.pack(">f", 25.0))
    client = _FakePlcnextModbusClient(registers=[hi, lo, 1, 0])
    monkeypatch.setattr(conn, "_build_modbus_client", lambda target: client)
    return TargetConfig(name="plcnext", protocol="modbus", host="127.0.0.1", port=502, unit_id=1)


@pytest.mark.unit
def test_plcnext_modbus_route_reads_process_value(plcnext_modbus):
    """The Modbus connector decodes a PLCnext-mapped float32 process value."""
    out = modbus_ops.modbus_read_holding(plcnext_modbus, address=0, count=2, decode="float32")
    assert out["decoded"][0] == pytest.approx(25.0)


@pytest.mark.unit
def test_plcnext_modbus_route_reads_word(plcnext_modbus):
    """A plain uint16 status word maps through the same route."""
    out = modbus_ops.modbus_read_holding(plcnext_modbus, address=2, count=1)
    assert out["decoded"] == [1]


# --------------------------------------------------------------------------- #
# Convenience profile + register template (enrichment)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_plcnext_profile_selects_opcua_and_modbus():
    """IAIOPS_MCP=plcnext exposes exactly the vPLC's two routes."""
    from mcp_server.profiles import resolve_selection

    assert resolve_selection("plcnext") == ["opcua", "modbus"]


@pytest.mark.unit
def test_plcnext_modbus_template_decodes_process_block():
    """The bundled PLCnext register template decodes a float32 process block."""
    from iaiops.connectors.modbus.templates import apply_template, get_template

    tmpl = get_template("phoenix_plcnext_process_be")
    assert tmpl.register_type == "holding"
    # Build a raw block: pv1=25.0 at offset 0 (ABCD float32), rest zero.
    regs = [0] * tmpl.span
    hi, lo = struct.unpack(">HH", struct.pack(">f", 25.0))
    regs[0], regs[1] = hi, lo
    out = apply_template("phoenix_plcnext_process_be", regs, start_address=0)
    by_tag = {t["tag"]: t for t in out["tags"]}
    assert by_tag["pv1"]["value"] == pytest.approx(25.0)
    assert "待核实" in out["caveat"]


# --------------------------------------------------------------------------- #
# Coverage declaration guard
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_plcnext_coverage_declared():
    """The runtime capability map declares PLCnext vPLC coverage on both routes."""
    protos = {p["protocol"]: p for p in protocols_supported()["protocols"]}
    for key in ("opcua", "modbus"):
        assert "PLCnext" in protos[key].get("requirements", "")
