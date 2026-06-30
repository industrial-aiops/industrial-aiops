"""HART-IP connector tests.

Two real layers + one mocked:
- **codec** (verified against the real ``hart-protocol`` lib): build a command frame
  and parse a crafted long-frame ACK back to the primary variable.
- **transport framing** (pure): HART-IP header pack/parse round-trip.
- **ops** end-to-end with the HART-IP wire transport monkeypatched (the transport is
  待核实 — no live gateway), feeding a crafted HART response through the real codec.
"""

from __future__ import annotations

import struct

import pytest

from iaiops.connectors.hart import codec
from iaiops.connectors.hart import transport as tx
from iaiops.core.runtime.config import TargetConfig

hart_protocol = pytest.importorskip("hart_protocol")  # the 'hart' extra


def _ack_frame(command_id: int, payload: bytes) -> bytes:
    """Craft a real HART long-frame ACK (delimiter 0x86) the codec can parse."""
    from hart_protocol.tools import calculate_checksum

    addr = (549755813888 | 0x8000).to_bytes(5, "big")
    core = b"\x86" + addr + bytes([command_id]) + bytes([len(payload)]) + payload
    cs = calculate_checksum(core)
    cs = cs if isinstance(cs, (bytes, bytearray)) else bytes([cs])
    return b"\xFF\xFF\xFF\xFF\xFF" + core + cs


# ── codec (verified against the real hart-protocol library) ───────────────────

@pytest.mark.unit
def test_build_command_produces_real_hart_frame():
    frame = codec.build_command("primary_variable")
    assert isinstance(frame, bytes) and frame.startswith(b"\xFF\xFF")
    assert b"\x82" in frame  # master-to-slave start delimiter


@pytest.mark.unit
def test_build_command_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown/unsupported HART read command"):
        codec.build_command("write_everything")


@pytest.mark.unit
def test_parse_responses_extracts_primary_variable():
    # 2 status bytes + PV unit code (7) + float32 85.0
    payload = bytes([0, 0, 7]) + struct.pack(">f", 85.0)
    messages = codec.parse_responses(_ack_frame(1, payload))
    assert len(messages) == 1
    assert messages[0].command == 1
    assert messages[0].primary_variable == pytest.approx(85.0)


# ── transport framing (pure, structurally testable) ───────────────────────────

@pytest.mark.unit
def test_hart_ip_frame_roundtrip():
    payload = b"\xFF\xFF\x82\x80\x00"
    msg = tx.frame_message(tx.MT_REQUEST, tx.MID_TOKEN_PASSING, 7, payload)
    parsed = tx.parse_message(msg)
    assert parsed["version"] == tx.HART_IP_VERSION
    assert parsed["message_type"] == tx.MT_REQUEST
    assert parsed["message_id"] == tx.MID_TOKEN_PASSING
    assert parsed["sequence"] == 7
    assert parsed["byte_count"] == tx.HEADER_LEN + len(payload)
    assert parsed["payload"] == payload


@pytest.mark.unit
def test_parse_message_rejects_short():
    with pytest.raises(ValueError, match="too short"):
        tx.parse_message(b"\x01\x00")


@pytest.mark.unit
def test_session_initiate_payload_shape():
    p = tx.session_initiate_payload(30)
    assert p == struct.pack(">BI", 1, 30000)


# ── ops end-to-end with the wire transport monkeypatched ──────────────────────

class _FakeSession:
    """Stands in for a live HART-IP gateway: returns a crafted HART response."""

    def __init__(self, response: bytes) -> None:
        self._response = response
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def send_hart_pdu(self, pdu: bytes) -> bytes:
        assert isinstance(pdu, bytes) and pdu  # the real command frame
        return self._response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def hart_target(monkeypatch):
    payload = bytes([0, 0, 7]) + struct.pack(">f", 85.0)
    session = _FakeSession(_ack_frame(1, payload))
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")
    return target, session


@pytest.mark.unit
def test_hart_primary_variable_end_to_end(hart_target):
    from iaiops.connectors.hart import ops

    target, session = hart_target
    out = ops.hart_primary_variable(target)
    assert out["endpoint"] == "xmtr-1"
    assert out["primary_variable"] == pytest.approx(85.0)
    assert out["command"] == 1
    assert session.opened and session.closed  # session lifecycle honored


@pytest.mark.unit
def test_hart_primary_variable_no_response(monkeypatch):
    from iaiops.connectors.hart import ops

    session = _FakeSession(b"")  # gateway returned nothing parseable
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    out = ops.hart_primary_variable(TargetConfig(name="x", protocol="hart", host="10.0.0.7"))
    assert "error" in out


def _hart_target_for(monkeypatch, response: bytes) -> TargetConfig:
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: _FakeSession(response))
    return TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")


@pytest.mark.unit
def test_hart_device_identity_end_to_end(monkeypatch):
    """cmd-0 fields the ops advertise must be POPULATED (guards fabricated reads)."""
    from iaiops.connectors.hart import ops

    payload = bytes([0, 0, 254, 0x60, 0x99, 4, 7, 5, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
    out = ops.hart_device_identity(_hart_target_for(monkeypatch, _ack_frame(0, payload)))
    assert out["manufacturer_id"] == 0x60
    assert out["device_type"] == 0x99      # was always None (read 'device_type')
    assert out["device_id"] is not None
    assert out["hart_revision"] == 7       # was always None (read 'universal_revision')


@pytest.mark.unit
def test_hart_dynamic_variables_end_to_end(monkeypatch):
    """cmd-3 loop current + PV/SV must be POPULATED (guards the fabricated read)."""
    from iaiops.connectors.hart import ops

    payload = (bytes([0, 0]) + struct.pack(">f", 4.2) + bytes([7])
               + struct.pack(">f", 85.0) + bytes([12]) + struct.pack(">f", 55.0))
    out = ops.hart_dynamic_variables(_hart_target_for(monkeypatch, _ack_frame(3, payload)))
    assert out["loop_current_mA"] == pytest.approx(4.2, abs=1e-3)  # was always None
    names = {v["name"]: v["value"] for v in out["variables"]}
    assert names["primary"] == pytest.approx(85.0)
    assert names["secondary"] == pytest.approx(55.0)
