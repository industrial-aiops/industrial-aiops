"""HART-IP connector tests.

Two real layers + one mocked:
- **codec** (verified against the real ``hart-protocol`` lib): build a command frame
  and parse a crafted long-frame ACK back to the primary variable.
- **transport framing** (pure): HART-IP header pack/parse round-trip.
- **ops** end-to-end with the HART-IP wire transport monkeypatched (the transport is
  待核实 — no live gateway), feeding a crafted HART response through the real codec.
"""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from iaiops.connectors.hart import codec
from iaiops.connectors.hart import transport as tx
from iaiops.core.runtime.config import TargetConfig, _hart_transport

hart_protocol = pytest.importorskip("hart_protocol")  # the 'hart' extra

# The transmitter's REAL 5-byte unique address (expanded device type + device id)
# used throughout: mfr 0x26, device type 0x06, device id 0x123456.
LONG_ADDR = bytes([0x26, 0x06, 0x12, 0x34, 0x56])
LONG_ADDR_TEXT = "26 06 12 34 56"
# What the wire carries: pack_command ORs in the primary-master bit (0x80).
LONG_ADDR_ON_WIRE = bytes([0xA6, 0x06, 0x12, 0x34, 0x56])

# Command-0 identity payload whose fields derive LONG_ADDR (2 status bytes, then
# 254, mfr id, device type, preambles, revisions ×4, flags, 3-byte device id).
IDENTITY_PAYLOAD = bytes([0, 0, 254, 0x26, 0x06, 5, 7, 5, 0, 0, 0, 0x12, 0x34, 0x56])


def _ack_frame(command_id: int, payload: bytes) -> bytes:
    """Craft a real HART long-frame ACK (delimiter 0x86) the codec can parse."""
    from hart_protocol.tools import calculate_checksum

    addr = (549755813888 | 0x8000).to_bytes(5, "big")
    core = b"\x86" + addr + bytes([command_id]) + bytes([len(payload)]) + payload
    cs = calculate_checksum(core)
    cs = cs if isinstance(cs, (bytes, bytearray)) else bytes([cs])
    return b"\xff\xff\xff\xff\xff" + core + cs


def _short_ack_frame(command_id: int, payload: bytes, poll_address: int = 0) -> bytes:
    """Craft a HART SHORT-frame ACK (delimiter 0x06) — a Command 0 poll answer."""
    from hart_protocol.tools import calculate_checksum

    core = (
        b"\x06"
        + bytes([0x80 | poll_address])
        + bytes([command_id])
        + bytes([len(payload)])
        + payload
    )
    cs = calculate_checksum(core)
    cs = cs if isinstance(cs, (bytes, bytearray)) else bytes([cs])
    return b"\xff\xff\xff\xff\xff" + core + cs


# ── codec (verified against the real hart-protocol library) ───────────────────


@pytest.mark.unit
def test_build_command_produces_real_hart_frame():
    frame = codec.build_command("primary_variable", LONG_ADDR)
    assert isinstance(frame, bytes) and frame.startswith(b"\xff\xff")
    assert frame[5] == 0x82  # master-to-slave long-frame start delimiter
    assert frame[6:11] == LONG_ADDR_ON_WIRE  # the REAL address, not a fabricated one


@pytest.mark.unit
def test_build_command_requires_an_address():
    """The fabricated default address is gone: an address must be supplied."""
    with pytest.raises(TypeError):
        codec.build_command("primary_variable")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="5 bytes"):
        codec.build_command("primary_variable", b"\x80\x00")


@pytest.mark.unit
def test_build_command_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown/unsupported HART read command"):
        codec.build_command("write_everything", LONG_ADDR)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text", ["26 06 12 34 56", "2606123456", "26:06:12:34:56", "26-06-12-34-56"]
)
def test_parse_long_address_accepts_hex_formats(text):
    assert codec.parse_long_address(text) == LONG_ADDR


@pytest.mark.unit
@pytest.mark.parametrize("text", ["", "26 06", "26 06 12 34 56 78", "zz 06 12 34 56"])
def test_parse_long_address_rejects_garbage(text):
    with pytest.raises(ValueError, match="10 hex digits"):
        codec.parse_long_address(text)


@pytest.mark.unit
def test_build_poll_command_is_a_short_frame():
    """hart-protocol only packs long frames; the Command 0 poll must be SHORT."""
    from hart_protocol.tools import calculate_checksum

    frame = codec.build_poll_command(0)
    assert frame[:5] == b"\xff" * 5
    core = frame[5:-1]
    assert core == bytes([0x02, 0x80, 0x00, 0x00])  # STX short, primary master, cmd 0
    assert frame[-1:] == calculate_checksum(core)
    assert codec.build_poll_command(3)[6] == 0x83  # polling address in the low bits


@pytest.mark.unit
def test_build_poll_command_rejects_bad_poll_address():
    with pytest.raises(ValueError, match="polling address"):
        codec.build_poll_command(64)
    with pytest.raises(ValueError, match="polling address"):
        codec.build_poll_command(-1)


@pytest.mark.unit
def test_unique_address_from_identity():
    """The 5-byte unique address is derived from a parsed Command 0 identity."""
    messages = codec.parse_responses(_short_ack_frame(0, IDENTITY_PAYLOAD))
    assert len(messages) == 1
    assert codec.unique_address_from_identity(messages[0]) == LONG_ADDR


@pytest.mark.unit
def test_unique_address_masks_manufacturer_bits():
    """Only the low 6 bits of the first identity byte enter the unique address."""
    payload = bytearray(IDENTITY_PAYLOAD)
    payload[3] = 0xE6  # 0xE6 & 0x3F == 0x26
    messages = codec.parse_responses(_short_ack_frame(0, bytes(payload)))
    assert codec.unique_address_from_identity(messages[0]) == LONG_ADDR


@pytest.mark.unit
def test_unique_address_from_identity_teaches_on_wrong_message():
    messages = codec.parse_responses(_ack_frame(1, bytes([0, 0, 7]) + struct.pack(">f", 85.0)))
    with pytest.raises(ValueError, match="long_address"):
        codec.unique_address_from_identity(messages[0])


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
    payload = b"\xff\xff\x82\x80\x00"
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


class _ScriptedSession:
    """Fake gateway answering from a scripted response queue; records every PDU."""

    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.sent: list[bytes] = []
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def send_hart_pdu(self, pdu: bytes) -> bytes:
        assert isinstance(pdu, bytes) and pdu
        self.sent.append(pdu)
        return self._responses.pop(0) if self._responses else b""

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def hart_target(monkeypatch):
    payload = bytes([0, 0, 7]) + struct.pack(">f", 85.0)
    session = _FakeSession(_ack_frame(1, payload))
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(
        name="xmtr-1", protocol="hart", host="10.0.0.7", long_address=LONG_ADDR_TEXT
    )
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
    out = ops.hart_primary_variable(
        TargetConfig(name="x", protocol="hart", host="10.0.0.7", long_address=LONG_ADDR_TEXT)
    )
    assert "error" in out


def _hart_target_for(monkeypatch, response: bytes) -> TargetConfig:
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: _FakeSession(response))
    return TargetConfig(
        name="xmtr-1", protocol="hart", host="10.0.0.7", long_address=LONG_ADDR_TEXT
    )


# ── identity → address chain (configured long_address / Command 0 discovery) ──


@pytest.mark.unit
def test_ops_send_the_configured_long_address(monkeypatch):
    """A configured long_address goes on the wire — never a fabricated default."""
    from iaiops.connectors.hart import ops

    payload = bytes([0, 0, 7]) + struct.pack(">f", 85.0)
    session = _ScriptedSession([_ack_frame(1, payload)])
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(
        name="xmtr-1", protocol="hart", host="10.0.0.7", long_address=LONG_ADDR_TEXT
    )
    out = ops.hart_primary_variable(target)
    assert out["primary_variable"] == pytest.approx(85.0)
    assert len(session.sent) == 1  # no discovery round-trip when configured
    frame = session.sent[0]
    assert frame[5] == 0x82
    assert frame[6:11] == LONG_ADDR_ON_WIRE


@pytest.mark.unit
def test_ops_discover_address_via_command0_poll(monkeypatch):
    """No long_address configured → short-frame Command 0 discovers the device,
    and the discovered unique address is used for the actual read."""
    from iaiops.connectors.hart import ops

    pv_payload = bytes([0, 0, 7]) + struct.pack(">f", 85.0)
    session = _ScriptedSession([_short_ack_frame(0, IDENTITY_PAYLOAD), _ack_frame(1, pv_payload)])
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")

    out = ops.hart_primary_variable(target)
    assert out["primary_variable"] == pytest.approx(85.0)
    assert len(session.sent) == 2
    poll, read = session.sent
    assert poll[5] == 0x02  # SHORT frame delimiter — the Command 0 identity poll
    assert poll[6] == 0x80  # primary master, polling address 0 (the default)
    assert poll[7] == 0x00  # Command 0
    assert read[5] == 0x82
    assert read[6:11] == LONG_ADDR_ON_WIRE  # the DISCOVERED address, on the wire


@pytest.mark.unit
def test_ops_discovery_failure_teaches_and_never_fabricates(monkeypatch):
    """Unconfigured + failed discovery → teaching error; no long frame is sent."""
    from iaiops.connectors.hart import ops
    from iaiops.core.runtime.connection import OTConnectionError

    session = _ScriptedSession([b""])  # the Command 0 poll goes unanswered
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")

    with pytest.raises(OTConnectionError, match="long_address"):
        ops.hart_primary_variable(target)
    assert all(frame[5] != 0x82 for frame in session.sent)  # no fabricated read


@pytest.mark.unit
def test_ops_invalid_configured_long_address_teaches(monkeypatch):
    from iaiops.connectors.hart import ops
    from iaiops.core.runtime.connection import OTConnectionError

    session = _ScriptedSession([])
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7", long_address="not-hex")
    with pytest.raises(OTConnectionError, match="10 hex digits"):
        ops.hart_primary_variable(target)
    assert session.sent == []  # nothing hit the wire with a bogus address


@pytest.mark.unit
def test_burst_sample_discovers_once_and_reuses_the_address(monkeypatch):
    """Discovery runs once per call (one poll), then every sample reuses it."""
    from iaiops.connectors.hart import ops

    cmd3_payload = (
        bytes([0, 0])
        + struct.pack(">f", 4.2)
        + bytes([7])
        + struct.pack(">f", 85.0)
        + bytes([12])
        + struct.pack(">f", 55.0)
    )
    session = _ScriptedSession(
        [_short_ack_frame(0, IDENTITY_PAYLOAD)] + [_ack_frame(3, cmd3_payload)] * 3
    )
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")

    out = ops.hart_burst_sample(target, samples=3)
    assert out["received_samples"] == 3
    assert len(session.sent) == 4  # 1 poll + 3 reads
    assert session.sent[0][5] == 0x02
    for frame in session.sent[1:]:
        assert frame[6:11] == LONG_ADDR_ON_WIRE


@pytest.mark.unit
def test_config_parses_hart_long_address(tmp_path):
    import iaiops.core.runtime.config as cfg

    path = tmp_path / "config.yaml"
    path.write_text(
        "endpoints:\n"
        "  - {name: xmtr, protocol: hart, host: 10.0.0.7, "
        "long_address: '26 06 12 34 56'}\n"
        "  - {name: bare, protocol: hart, host: 10.0.0.8}\n"
    )
    config = cfg.load_config(path)
    assert config.get_target("xmtr").long_address == "26 06 12 34 56"
    assert config.get_target("bare").long_address == ""  # optional, default empty


@pytest.mark.unit
def test_hart_device_identity_end_to_end(monkeypatch):
    """cmd-0 fields the ops advertise must be POPULATED (guards fabricated reads)."""
    from iaiops.connectors.hart import ops

    payload = bytes([0, 0, 254, 0x60, 0x99, 4, 7, 5, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
    out = ops.hart_device_identity(_hart_target_for(monkeypatch, _ack_frame(0, payload)))
    assert out["manufacturer_id"] == 0x60
    assert out["device_type"] == 0x99  # was always None (read 'device_type')
    assert out["device_id"] is not None
    assert out["hart_revision"] == 7  # was always None (read 'universal_revision')


@pytest.mark.unit
def test_hart_dynamic_variables_end_to_end(monkeypatch):
    """cmd-3 loop current + PV/SV must be POPULATED (guards the fabricated read)."""
    from iaiops.connectors.hart import ops

    payload = (
        bytes([0, 0])
        + struct.pack(">f", 4.2)
        + bytes([7])
        + struct.pack(">f", 85.0)
        + bytes([12])
        + struct.pack(">f", 55.0)
    )
    out = ops.hart_dynamic_variables(_hart_target_for(monkeypatch, _ack_frame(3, payload)))
    assert out["loop_current_mA"] == pytest.approx(4.2, abs=1e-3)  # was always None
    names = {v["name"]: v["value"] for v in out["variables"]}
    assert names["primary"] == pytest.approx(85.0)
    assert names["secondary"] == pytest.approx(55.0)


@pytest.mark.unit
def test_hart_burst_sample_collects_multiple(monkeypatch):
    """Burst sampling reads the published (cmd-3) variables N times over one session."""
    from iaiops.connectors.hart import ops

    payload = (
        bytes([0, 0])
        + struct.pack(">f", 4.2)
        + bytes([7])
        + struct.pack(">f", 85.0)
        + bytes([12])
        + struct.pack(">f", 55.0)
    )
    session = _FakeSession(_ack_frame(3, payload))
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(
        name="xmtr-1", protocol="hart", host="10.0.0.7", long_address=LONG_ADDR_TEXT
    )

    out = ops.hart_burst_sample(target, samples=3)
    assert out["endpoint"] == "xmtr-1"
    assert out["requested_samples"] == 3
    assert out["received_samples"] == 3
    assert len(out["samples"]) == 3
    first = out["samples"][0]
    assert first["index"] == 0
    assert first["loop_current_mA"] == pytest.approx(4.2, abs=1e-3)
    names = {v["name"]: v["value"] for v in first["variables"]}
    assert names["primary"] == pytest.approx(85.0)
    assert names["secondary"] == pytest.approx(55.0)
    assert "待核实" in out["note"]
    assert session.opened and session.closed  # one session for all samples


@pytest.mark.unit
def test_hart_burst_sample_bounds_and_reports_no_response(monkeypatch):
    """Sample count is clamped (>=1) and unparseable reads are flagged, not dropped."""
    from iaiops.connectors.hart import ops

    session = _FakeSession(b"")  # gateway returns nothing parseable
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="x", protocol="hart", host="10.0.0.7", long_address=LONG_ADDR_TEXT)

    out = ops.hart_burst_sample(target, samples=0)  # clamped up to 1
    assert out["requested_samples"] == 1
    assert out["received_samples"] == 0
    assert out["samples"][0]["error"]


@pytest.mark.unit
def test_hart_burst_sample_tool_is_governed_low():
    from mcp_server.tools.hart_tools import hart_burst_sample as tool

    assert getattr(tool, "_is_governed_tool", False) is True
    assert getattr(tool, "_risk_level", "") == "low"


# ── HART-IP response validation (type/id/sequence match + header status) ──────


class _FakeUdpSocket:
    """A scripted UDP socket: returns queued datagrams, then times out."""

    def __init__(self, datagrams: list[bytes]) -> None:
        self._datagrams = list(datagrams)
        self.sent: list[bytes] = []

    def settimeout(self, timeout: float) -> None:
        pass

    def sendto(self, data: bytes, addr) -> None:
        self.sent.append(data)

    def recvfrom(self, bufsize: int):
        if not self._datagrams:
            raise TimeoutError("timed out")
        return self._datagrams.pop(0), ("10.0.0.7", 5094)

    def close(self) -> None:
        pass


@pytest.mark.unit
def test_udp_session_skips_stale_and_mismatched_datagrams():
    """A stale response, a keep-alive, and a runt arrive first; the session must
    keep reading until the datagram matching THIS request's type/id/seq."""
    stale = tx.frame_message(tx.MT_RESPONSE, tx.MID_TOKEN_PASSING, 999, b"old")
    keepalive = tx.frame_message(tx.MT_RESPONSE, tx.MID_KEEP_ALIVE, 1, b"")
    good = tx.frame_message(tx.MT_RESPONSE, tx.MID_TOKEN_PASSING, 1, b"new")
    session = tx.HartIpSession("10.0.0.7", 5094, timeout_s=1.0)
    session._sock = _FakeUdpSocket([b"\x01", stale, keepalive, good])

    assert session.send_hart_pdu(b"pdu") == b"new"


@pytest.mark.unit
def test_udp_session_times_out_when_no_datagram_matches():
    from iaiops.core.runtime.connection import OTConnectionError

    stale = tx.frame_message(tx.MT_RESPONSE, tx.MID_TOKEN_PASSING, 999, b"old")
    session = tx.HartIpSession("10.0.0.7", 5094, timeout_s=0.2)
    session._sock = _FakeUdpSocket([stale])

    with pytest.raises(OTConnectionError, match="no matching"):
        session.send_hart_pdu(b"pdu")


@pytest.mark.unit
def test_udp_session_surfaces_error_status():
    """A non-zero HART-IP header status is a real error — never an empty parse
    that reads as 'device/gateway unreachable'."""
    from iaiops.core.runtime.connection import OTConnectionError

    bad = bytearray(tx.frame_message(tx.MT_RESPONSE, tx.MID_TOKEN_PASSING, 1, b""))
    bad[3] = 14  # header status byte
    session = tx.HartIpSession("10.0.0.7", 5094, timeout_s=1.0)
    session._sock = _FakeUdpSocket([bytes(bad)])

    with pytest.raises(OTConnectionError, match="status 14"):
        session.send_hart_pdu(b"pdu")


class _FakeTcpSocket:
    """A scripted TCP stream socket: serves a fixed byte buffer."""

    def __init__(self, data: bytes) -> None:
        self._buf = data
        self.sent = b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, n: int) -> bytes:
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk


@pytest.mark.unit
def test_tcp_session_skips_unsolicited_then_matches():
    unsolicited = tx.frame_message(tx.MT_RESPONSE, tx.MID_KEEP_ALIVE, 0, b"")
    good = tx.frame_message(tx.MT_RESPONSE, tx.MID_TOKEN_PASSING, 1, b"resp")
    session = tx.HartIpTcpSession("10.0.0.7", 5094, timeout_s=1.0)
    session._sock = _FakeTcpSocket(unsolicited + good)

    assert session.send_hart_pdu(b"pdu") == b"resp"


@pytest.mark.unit
def test_tcp_session_surfaces_error_status():
    from iaiops.core.runtime.connection import OTConnectionError

    bad = bytearray(tx.frame_message(tx.MT_RESPONSE, tx.MID_TOKEN_PASSING, 1, b""))
    bad[3] = 5  # header status byte
    session = tx.HartIpTcpSession("10.0.0.7", 5094, timeout_s=1.0)
    session._sock = _FakeTcpSocket(bytes(bad))

    with pytest.raises(OTConnectionError, match="status 5"):
        session.send_hart_pdu(b"pdu")


# ── transport selection (udp default / tcp opt-in) ────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "given,expected",
    [("", "udp"), ("udp", "udp"), ("UDP", "udp"), ("tcp", "tcp"), ("TCP", "tcp")],
)
def test_hart_transport_resolves(given, expected):
    assert _hart_transport({"transport": given}) == expected


@pytest.mark.unit
def test_build_hart_ip_client_selects_session_class():
    udp = tx._build_hart_ip_client(
        TargetConfig(name="u", protocol="hart", host="10.0.0.7", transport="udp")
    )
    tcp = tx._build_hart_ip_client(
        TargetConfig(name="t", protocol="hart", host="10.0.0.7", transport="tcp")
    )
    assert isinstance(udp, tx.HartIpSession)
    assert isinstance(tcp, tx.HartIpTcpSession)


# ── TCP transport: real localhost loopback through the REAL ops/codec path ─────


class _HartIpTcpServer:
    """A tiny in-process HART-IP TCP server speaking the 8-byte framing.

    It reads a framed request (length-delimited by the header byte_count exactly
    like the client must), then replies with a framed response: an empty body for
    session-initiate/close, and the crafted HART long-frame ACK for token-passing.
    Bounded to a single connection; joined + closed in teardown.
    """

    def __init__(self, ack: bytes) -> None:
        self._ack = ack
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self._srv.settimeout(5.0)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    @staticmethod
    def _recv_exactly(conn: socket.socket, n: int) -> bytes:
        chunks: list[bytes] = []
        got = 0
        while got < n:
            chunk = conn.recv(n - got)
            if not chunk:
                return b""
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def _serve(self) -> None:
        conn, _ = self._srv.accept()
        try:
            conn.settimeout(5.0)
            while True:
                header = self._recv_exactly(conn, tx.HEADER_LEN)
                if len(header) < tx.HEADER_LEN:
                    return
                meta = tx.parse_message(header)
                body_len = meta["byte_count"] - tx.HEADER_LEN
                if body_len:
                    self._recv_exactly(conn, body_len)
                if meta["message_id"] == tx.MID_TOKEN_PASSING:
                    payload = self._ack
                else:
                    payload = b""
                conn.sendall(
                    tx.frame_message(tx.MT_RESPONSE, meta["message_id"], meta["sequence"], payload)
                )
                if meta["message_id"] == tx.MID_SESSION_CLOSE:
                    return
        finally:
            conn.close()

    def close(self) -> None:
        self._srv.close()
        self._thread.join(timeout=5.0)


@pytest.fixture
def hart_tcp_server():
    payload = bytes([0, 0, 7]) + struct.pack(">f", 85.0)
    server = _HartIpTcpServer(_ack_frame(1, payload))
    server.start()
    try:
        yield server
    finally:
        server.close()


@pytest.mark.unit
def test_hart_tcp_transport_loopback_to_primary_variable(hart_tcp_server):
    """Real TCP socket round-trip: the TCP session length-delimits the stream by the
    header byte_count and feeds the response through the REAL ops/codec path."""
    from iaiops.connectors.hart import ops

    target = TargetConfig(
        name="xmtr-tcp",
        protocol="hart",
        host="127.0.0.1",
        port=hart_tcp_server.port,
        transport="tcp",
        long_address=LONG_ADDR_TEXT,
    )
    out = ops.hart_primary_variable(target)
    assert out["endpoint"] == "xmtr-tcp"
    assert out["command"] == 1
    assert out["primary_variable"] == pytest.approx(85.0)


@pytest.mark.unit
def test_hart_tcp_session_length_delimits_split_response(hart_tcp_server):
    """Lower-level: drive HartIpTcpSession directly to prove header-then-body reads."""
    session = tx.HartIpTcpSession("127.0.0.1", hart_tcp_server.port)
    session.open()
    try:
        raw = session.send_hart_pdu(codec.build_command("primary_variable", LONG_ADDR))
    finally:
        session.close()
    messages = codec.parse_responses(raw)
    assert messages and messages[0].command == 1
    assert messages[0].primary_variable == pytest.approx(85.0)


class _BurstSession:
    """Fake gateway that answers the Command-0 discovery poll, then PUBLISHES
    HART-IP burst messages (message_type 2) on receive_message()."""

    def __init__(self, publishes):
        self._publishes = list(publishes)
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def send_hart_pdu(self, pdu):
        # only the Command-0 discovery poll is sent by the listener
        return _short_ack_frame(0, IDENTITY_PAYLOAD)

    def receive_message(self, timeout_s):
        if self._publishes:
            return self._publishes.pop(0)
        return None  # timeout — nothing more to publish

    def close(self):
        self.closed = True


def _cmd3_publish(pv=85.0):
    """A HART-IP publish message (type 2) carrying a command-3 ACK payload."""
    payload = (
        bytes([0, 0])
        + struct.pack(">f", 4.2)
        + bytes([7])
        + struct.pack(">f", pv)
        + bytes([12])
        + struct.pack(">f", 55.0)
    )
    return {"message_type": tx.MT_PUBLISH, "payload": _ack_frame(3, payload)}


@pytest.mark.unit
def test_burst_listen_collects_published_messages(monkeypatch):
    from iaiops.connectors.hart import ops

    session = _BurstSession([_cmd3_publish(85.0), _cmd3_publish(86.0)])
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")

    out = ops.hart_burst_listen(target, duration_s=5, max_messages=10)
    assert out["received_messages"] == 2
    pvs = [m["variables"][0]["value"] for m in out["messages"]]
    assert pvs[0] == pytest.approx(85.0)
    assert pvs[1] == pytest.approx(86.0)


@pytest.mark.unit
def test_burst_listen_ignores_non_publish_messages(monkeypatch):
    from iaiops.connectors.hart import ops

    keepalive = {"message_type": tx.MT_RESPONSE, "payload": b""}
    session = _BurstSession([keepalive, _cmd3_publish(90.0)])
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")

    out = ops.hart_burst_listen(target, duration_s=5, max_messages=10)
    assert out["received_messages"] == 1  # keep-alive skipped, only the publish counts


@pytest.mark.unit
def test_burst_listen_stops_at_max_messages(monkeypatch):
    from iaiops.connectors.hart import ops

    session = _BurstSession([_cmd3_publish() for _ in range(5)])
    monkeypatch.setattr(tx, "_build_hart_ip_client", lambda target: session)
    target = TargetConfig(name="xmtr-1", protocol="hart", host="10.0.0.7")

    out = ops.hart_burst_listen(target, duration_s=30, max_messages=2)
    assert out["received_messages"] == 2


# ── receive_message hardening (burst-listener transport paths) ────────────────


class _FakeUdpSock:
    def __init__(self, datagrams):
        self._datagrams = list(datagrams)
        self._timeout = None

    def gettimeout(self):
        return self._timeout

    def settimeout(self, value):
        self._timeout = value

    def recvfrom(self, size):
        if not self._datagrams:
            raise TimeoutError
        return self._datagrams.pop(0), ("10.0.0.7", 5094)


class _FakeTcpSock:
    """Byte-stream double: script items are bytes chunks or the string 'timeout'."""

    def __init__(self, script):
        self._script = list(script)
        self._timeout = None

    def gettimeout(self):
        return self._timeout

    def settimeout(self, value):
        self._timeout = value

    def recv(self, size):
        if not self._script:
            raise TimeoutError
        item = self._script[0]
        if item == "timeout":
            self._script.pop(0)
            raise TimeoutError
        chunk, rest = item[:size], item[size:]
        if rest:
            self._script[0] = rest
        else:
            self._script.pop(0)
        return chunk


@pytest.mark.unit
def test_udp_receive_skips_garbage_datagram_instead_of_aborting():
    publish = tx.frame_message(tx.MT_PUBLISH, tx.MID_TOKEN_PASSING, 1, b"\x01\x02")
    session = tx.HartIpSession("10.0.0.7", 5094)
    session._sock = _FakeUdpSock([b"junk", publish])
    assert session.receive_message(0.1) is None  # runt datagram → skipped, not raised
    parsed = session.receive_message(0.1)
    assert parsed["message_type"] == tx.MT_PUBLISH
    assert session.receive_message(0.1) is None  # silence → None


@pytest.mark.unit
def test_tcp_receive_none_on_pure_silence():
    session = tx.HartIpTcpSession("10.0.0.7", 5094)
    session._sock = _FakeTcpSock(["timeout"])
    assert session.receive_message(0.1) is None


@pytest.mark.unit
def test_tcp_receive_mid_frame_timeout_is_a_desync_error_not_none():
    """One header byte arrives, then the stream stalls: returning None here would
    leave the consumed byte unaccounted for and desynchronize every later read."""
    session = tx.HartIpTcpSession("10.0.0.7", 5094)
    session._sock = _FakeTcpSock([b"\x01", "timeout"])
    with pytest.raises(tx.OTConnectionError, match="MID-FRAME"):
        session.receive_message(0.1)


@pytest.mark.unit
def test_tcp_receive_reassembles_a_fragmented_frame():
    frame = tx.frame_message(tx.MT_PUBLISH, tx.MID_TOKEN_PASSING, 2, b"\xaa\xbb\xcc")
    session = tx.HartIpTcpSession("10.0.0.7", 5094)
    session._sock = _FakeTcpSock([frame[:3], frame[3:9], frame[9:]])
    parsed = session.receive_message(0.1)
    assert (parsed["message_type"], parsed["payload"]) == (tx.MT_PUBLISH, b"\xaa\xbb\xcc")


@pytest.mark.unit
def test_tcp_receive_closed_while_listening_raises():
    session = tx.HartIpTcpSession("10.0.0.7", 5094)
    session._sock = _FakeTcpSock([b""])
    with pytest.raises(tx.OTConnectionError, match="closed while"):
        session.receive_message(0.1)
