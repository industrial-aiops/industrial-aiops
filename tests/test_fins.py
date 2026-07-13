"""Omron FINS connector tests against an in-repo mock FINS responder.

The mock responder (UDP + TCP) is the connector's declared self-test: it
speaks real FINS framing (10-byte header, 0101/0102/0501/0601 commands, end
codes; FINS/TCP adds the 16-byte header + node handshake), so these tests
exercise the actual stdlib wire client end-to-end on loopback — frame
round-trips, SID matching, end-code mapping, area code encoding, caps, the
write dry-run/apply/undo path, and the session guard/translate lifecycle.
Live Omron PLC behaviour remains 待核实.
"""

from __future__ import annotations

import socket
import struct
import threading

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.fins import client as fins_client
from iaiops.connectors.fins import ops
from iaiops.connectors.fins.client import (
    FINS_TCP_HEADER,
    FINS_TCP_MAGIC,
    FinsEndCodeError,
    FinsFramingError,
    FinsUdpClient,
    build_fins_frame,
    parse_fins_response,
    resolve_area,
)
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import OTConnectionError


# ---------------------------------------------------------------------------
# Mock FINS responder — shared command handling for UDP and TCP.
# ---------------------------------------------------------------------------
class _FinsPlcModel:
    """A tiny in-memory Omron PLC: DM/CIO words + a run/stop status."""

    def __init__(self) -> None:
        self.words: dict[tuple[int, int], int] = {  # (area_code, address) -> value
            (0x82, 100): 10, (0x82, 101): 20, (0x82, 102): 30,  # DM100..102
            (0xB0, 0): 0x0005,  # CIO 0 → bits 0 and 2 set
        }
        self.force_end_code: bytes | None = None
        self.tamper_sid: int | None = None  # respond with a wrong SID

    def handle(self, frame: bytes) -> bytes | None:
        """Given a raw FINS command frame, produce the response frame."""
        if len(frame) < 12:
            return None
        _icf, _rsv, gct = frame[0], frame[1], frame[2]
        dna, da1, da2, sna, sa1, sa2, sid = frame[3:10]
        mrc, src = frame[10], frame[11]
        body = frame[12:]
        if self.tamper_sid is not None:
            sid = self.tamper_sid
        end = self.force_end_code if self.force_end_code is not None else b"\x00\x00"
        # Response header: swap source/destination, set the response ICF bit.
        header = bytes((0xC0, 0x00, gct, sna, sa1, sa2, dna, da1, da2, sid))
        payload = b""
        if end == b"\x00\x00":
            if (mrc, src) == (0x01, 0x01):  # memory area read
                area, addr, bit, count = struct.unpack(">BHBH", body[:6])
                if bit_code_is_bit(area):
                    payload = bytes(
                        (self.words.get((word_of(area), addr), 0) >> (bit + i)) & 1
                        for i in range(count)
                    )
                else:
                    payload = b"".join(
                        struct.pack(">H", self.words.get((area, addr + i), 0))
                        for i in range(count)
                    )
            elif (mrc, src) == (0x01, 0x02):  # memory area write
                area, addr, _bit, count = struct.unpack(">BHBH", body[:6])
                values = struct.unpack(f">{count}H", body[6 : 6 + 2 * count])
                for i, v in enumerate(values):
                    self.words[(area, addr + i)] = v
            elif (mrc, src) == (0x05, 0x01):  # controller data read
                payload = b"CJ2M-CPU31".ljust(20, b"\x00") + b"04.10".ljust(20, b"\x00")
            elif (mrc, src) == (0x06, 0x01):  # controller status read
                payload = struct.pack(">BBHH", 0x01, 0x04, 0, 0)  # run / RUN mode
            else:
                end = b"\x04\x01"  # undefined command
        return header + bytes((mrc, src)) + end + payload


def bit_code_is_bit(area_code: int) -> bool:
    return area_code in (0x30, 0x31, 0x32, 0x33, 0x02)


def word_of(bit_code: int) -> int:
    return {0x30: 0xB0, 0x31: 0xB1, 0x32: 0xB2, 0x33: 0xB3, 0x02: 0x82}[bit_code]


class MockFinsUdpServer:
    """Threaded UDP FINS responder bound to 127.0.0.1:<ephemeral>."""

    def __init__(self) -> None:
        self.plc = _FinsPlcModel()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            response = self.plc.handle(data)
            if response is not None:
                self._sock.sendto(response, addr)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()


class MockFinsTcpServer:
    """Threaded FINS/TCP responder: node handshake + length-delimited frames.

    ``reject_handshake=True`` answers the node-address handshake with FINS/TCP
    error 0x25 ("all node addresses in use") instead of assigning a node.
    """

    def __init__(self, *, reject_handshake: bool = False) -> None:
        self.reject_handshake = reject_handshake
        self.plc = _FinsPlcModel()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._sock.settimeout(5)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn_sock, _ = self._sock.accept()
        except OSError:
            return
        with conn_sock:
            conn_sock.settimeout(5)
            try:
                while True:
                    header = self._recv_exactly(conn_sock, FINS_TCP_HEADER.size)
                    _magic, length, command, _err = FINS_TCP_HEADER.unpack(header)
                    body = self._recv_exactly(conn_sock, length - 8)
                    if command == 0:  # handshake: assign client node 42, server 1
                        if self.reject_handshake:
                            reply = FINS_TCP_HEADER.pack(FINS_TCP_MAGIC, 8, 3, 0x25)
                            conn_sock.sendall(reply)
                            return
                        reply = FINS_TCP_HEADER.pack(FINS_TCP_MAGIC, 16, 1, 0)
                        conn_sock.sendall(reply + struct.pack(">II", 42, 1))
                    elif command == 2:
                        response = self.plc.handle(body)
                        if response is not None:
                            reply = FINS_TCP_HEADER.pack(
                                FINS_TCP_MAGIC, 8 + len(response), 2, 0
                            )
                            conn_sock.sendall(reply + response)
            except (OSError, FinsFramingError):
                return

    @staticmethod
    def _recv_exactly(sock: socket.socket, n: int) -> bytes:
        chunks = b""
        while len(chunks) < n:
            chunk = sock.recv(n - len(chunks))
            if not chunk:
                raise FinsFramingError("mock: connection closed")
            chunks += chunk
        return chunks

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def udp_server():
    server = MockFinsUdpServer()
    yield server
    server.close()


@pytest.fixture
def fins_target(udp_server):
    return TargetConfig(
        name="omron1", protocol="fins", host="127.0.0.1",
        port=udp_server.port, timeout_s=2.0,
    ), udp_server


# ---------------------------------------------------------------------------
# Pure framing / encoding.
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_frame_layout_and_roundtrip():
    frame = build_fins_frame(sid=7, da1=10, sa1=1, command=b"\x01\x01\x82\x00\x64\x00\x00\x02")
    assert frame[0] == 0x80  # ICF: command, response required
    assert frame[2] == 0x02  # GCT
    assert frame[4] == 10 and frame[7] == 1 and frame[9] == 7
    assert frame[10:12] == b"\x01\x01"
    # A matching response parses back to its payload.
    response = bytes((0xC0, 0, 2, 0, 1, 0, 0, 10, 0, 7)) + b"\x01\x01\x00\x00" + b"\x12\x34"
    assert parse_fins_response(response, expect_sid=7, expect_mrc=0x01,
                               expect_src=0x01) == b"\x12\x34"


@pytest.mark.unit
def test_area_code_encoding():
    assert resolve_area("DM").word_code == 0x82
    assert resolve_area("dm").bit_code == 0x02
    assert resolve_area("CIO").word_code == 0xB0
    assert resolve_area("CIO").bit_code == 0x30
    assert resolve_area("W").word_code == 0xB1
    assert resolve_area("H").word_code == 0xB2
    assert resolve_area("A").word_code == 0xB3
    assert resolve_area("EM").word_code == 0x98
    with pytest.raises(ValueError, match="Unknown FINS memory area"):
        resolve_area("ZZ")
    with pytest.raises(ValueError, match="no bit-access"):
        resolve_area("EM", bit_access=True)


@pytest.mark.unit
def test_sid_mismatch_rejected():
    response = bytes((0xC0, 0, 2, 0, 1, 0, 0, 10, 0, 99)) + b"\x01\x01\x00\x00"
    with pytest.raises(FinsFramingError, match="SID mismatch"):
        parse_fins_response(response, expect_sid=7, expect_mrc=0x01, expect_src=0x01)


@pytest.mark.unit
def test_end_code_error_mapping():
    response = bytes((0xC0, 0, 2, 0, 1, 0, 0, 10, 0, 7)) + b"\x01\x01\x11\x03"
    with pytest.raises(FinsEndCodeError, match="address range error") as exc_info:
        parse_fins_response(response, expect_sid=7, expect_mrc=0x01, expect_src=0x01)
    assert exc_info.value.end_code == 0x1103
    # Flag bits (relay error / CPU error flags) are stripped from the code.
    flagged = bytes((0xC0, 0, 2, 0, 1, 0, 0, 10, 0, 7)) + b"\x01\x01\x91\x43"
    with pytest.raises(FinsEndCodeError) as exc_info:
        parse_fins_response(flagged, expect_sid=7, expect_mrc=0x01, expect_src=0x01)
    assert exc_info.value.end_code == 0x1103
    assert exc_info.value.relay_error is True
    assert exc_info.value.non_fatal_cpu_error is True


@pytest.mark.unit
def test_short_and_non_response_frames_rejected():
    with pytest.raises(FinsFramingError, match="too short"):
        parse_fins_response(b"\xc0\x00", expect_sid=1, expect_mrc=1, expect_src=1)
    command_frame = build_fins_frame(sid=1, command=b"\x01\x01\x00\x00")
    with pytest.raises(FinsFramingError, match="not a response"):
        parse_fins_response(command_frame, expect_sid=1, expect_mrc=0x01, expect_src=0x01)


# ---------------------------------------------------------------------------
# Ops end-to-end over the mock UDP responder.
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_fins_cpu_info_roundtrip(fins_target):
    target, _ = fins_target
    out = ops.fins_cpu_info(target)
    assert out["model"] == "CJ2M-CPU31"
    assert out["version"] == "04.10"


@pytest.mark.integration
def test_fins_cpu_status_roundtrip(fins_target):
    target, _ = fins_target
    out = ops.fins_cpu_status(target)
    assert out["status"] == "run"
    assert out["mode"] == "RUN"
    assert out["fatal_error_data"] == 0


@pytest.mark.integration
def test_fins_read_words_roundtrip(fins_target):
    target, _ = fins_target
    out = ops.fins_read_words(target, "DM", 100, count=3)
    assert out["area"] == "DM"
    assert out["words"] == [10, 20, 30]


@pytest.mark.integration
def test_fins_read_bits_roundtrip(fins_target):
    target, _ = fins_target
    out = ops.fins_read_bits(target, "CIO", 0, bit=0, count=3)
    assert out["bits"] == [True, False, True]  # CIO 0 = 0x0005


@pytest.mark.integration
def test_fins_read_many_roundtrip(fins_target):
    target, _ = fins_target
    out = ops.fins_read_many(target, [
        {"area": "DM", "address": 100, "count": 2},
        {"area": "CIO", "address": 0, "count": 1},
    ])
    assert out["reads"][0]["words"] == [10, 20]
    assert out["reads"][1]["words"] == [5]


@pytest.mark.unit
def test_fins_read_many_validates_items(fins_target):
    target, _ = fins_target
    assert "error" in ops.fins_read_many(target, [])
    with pytest.raises(ValueError, match="must be dicts"):
        ops.fins_read_many(target, ["DM100"])


@pytest.mark.unit
def test_read_count_caps(fins_target):
    target, _ = fins_target
    out = ops.fins_read_words(target, "DM", 100, count=99999)
    assert out["count"] == ops.MAX_WORDS == 500
    out = ops.fins_read_bits(target, "CIO", 0, count=99999)
    assert out["count"] == ops.MAX_BITS == 256


@pytest.mark.integration
def test_fins_write_dry_run_captures_before_and_writes_nothing(fins_target):
    target, server = fins_target
    out = ops.fins_write_words(target, "DM", 100, [1, 2], dry_run=True)
    assert out["dry_run"] is True
    assert out["before"] == [10, 20]
    assert out["would_write"] == [1, 2]
    assert server.plc.words[(0x82, 100)] == 10  # untouched


@pytest.mark.integration
def test_fins_write_applied_and_end_code_surfacing(fins_target):
    target, server = fins_target
    out = ops.fins_write_words(target, "DM", 100, [1, 2], dry_run=False)
    assert out["applied"] is True
    assert out["before"] == [10, 20]
    assert server.plc.words[(0x82, 100)] == 1
    assert server.plc.words[(0x82, 101)] == 2
    # A PLC end code surfaces as a translated OTConnectionError.
    server.plc.force_end_code = b"\x21\x01"
    with pytest.raises(OTConnectionError, match="read-only area"):
        ops.fins_read_words(target, "DM", 100)


@pytest.mark.integration
def test_udp_client_rejects_tampered_sid(fins_target):
    target, server = fins_target
    server.plc.tamper_sid = 250
    with pytest.raises(OTConnectionError, match="SID mismatch"):
        ops.fins_read_words(target, "DM", 100)


@pytest.mark.integration
def test_fins_tcp_handshake_and_read():
    server = MockFinsTcpServer()
    try:
        target = TargetConfig(
            name="omron-tcp", protocol="fins", host="127.0.0.1",
            port=server.port, transport="tcp", timeout_s=2.0,
        )
        out = ops.fins_read_words(target, "DM", 100, count=3)
        assert out["words"] == [10, 20, 30]
    finally:
        server.close()


@pytest.mark.integration
def test_fins_tcp_handshake_failure_closes_socket():
    """A failed node-address handshake must not leak the TCP socket.

    Regression: connect() left self._sock open when the handshake raised, and
    the session factory skips teardown on connect failure — in the long-lived
    MCP server that leaked one FD per call, and the 0x25 "all node addresses
    in use" case was self-reinforcing (half-open conns held server node slots).
    """
    server = MockFinsTcpServer(reject_handshake=True)
    try:
        client = fins_client.FinsTcpClient("127.0.0.1", server.port, timeout_s=2.0)
        with pytest.raises(fins_client.FinsError, match="0x00000025"):
            client.connect()
        assert client._sock is None  # socket closed + state reset, no FD leak
    finally:
        server.close()


@pytest.mark.integration
def test_fins_tcp_handshake_garbage_reply_closes_socket():
    """A framing error during the handshake must also close the socket."""

    class _GarbageServer(MockFinsTcpServer):
        def _serve(self) -> None:
            try:
                conn_sock, _ = self._sock.accept()
            except OSError:
                return
            with conn_sock:
                conn_sock.sendall(b"NOTFINS!" + b"\x00" * 8)

    server = _GarbageServer()
    try:
        client = fins_client.FinsTcpClient("127.0.0.1", server.port, timeout_s=2.0)
        with pytest.raises(FinsFramingError, match="magic mismatch"):
            client.connect()
        assert client._sock is None
    finally:
        server.close()


# ---------------------------------------------------------------------------
# Session guard / translate / transport selection.
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_session_rejects_wrong_protocol():
    target = TargetConfig(name="x", protocol="modbus", host="10.0.0.9")
    with pytest.raises(OTConnectionError, match="not fins"):
        with conn.fins_session(target):
            pass


@pytest.mark.unit
def test_build_requires_host():
    target = TargetConfig(name="x", protocol="fins")
    with pytest.raises(OTConnectionError, match="has no host"):
        with conn.fins_session(target):
            pass


@pytest.mark.unit
def test_build_selects_transport():
    udp = conn._build_fins_client(
        TargetConfig(name="u", protocol="fins", host="10.0.0.9"))
    assert isinstance(udp, fins_client.FinsUdpClient)
    tcp = conn._build_fins_client(
        TargetConfig(name="t", protocol="fins", host="10.0.0.9", transport="tcp"))
    assert isinstance(tcp, fins_client.FinsTcpClient)


@pytest.mark.unit
def test_udp_node_defaults_to_ip_last_octet():
    client = FinsUdpClient("10.0.0.9")
    assert client._da1 == 9
    assert FinsUdpClient("plc.local")._da1 == 0


@pytest.mark.unit
def test_translate_teaches(monkeypatch):
    class _Boom:
        def connect(self):
            raise TimeoutError("timed out")

        def close(self):
            pass

    monkeypatch.setattr(conn, "_build_fins_client", lambda target: _Boom())
    target = TargetConfig(name="omron1", protocol="fins", host="10.0.0.9")
    with pytest.raises(OTConnectionError, match="FINS/UDP") as exc_info:
        with conn.fins_session(target):
            pass
    assert exc_info.value.protocol == "fins"
    assert "9600" in str(exc_info.value)


@pytest.mark.unit
def test_session_monkeypatch_point(monkeypatch, udp_server):
    """conn._build_fins_client stays the documented late-bound patch point."""
    built = []

    def _fake_build(target):
        client = FinsUdpClient("127.0.0.1", udp_server.port, timeout_s=2.0)
        built.append(client)
        return client

    monkeypatch.setattr(conn, "_build_fins_client", _fake_build)
    target = TargetConfig(name="omron1", protocol="fins", host="ignored.example")
    out = ops.fins_read_words(target, "DM", 100)
    assert out["words"] == [10]
    assert built, "session did not resolve the patched factory"


# ---------------------------------------------------------------------------
# Governance markers + undo descriptor on the MCP tool surface.
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_fins_tools_are_governed():
    from mcp_server.tools import fins_tools

    for name in ("fins_cpu_info", "fins_cpu_status", "fins_read_words",
                 "fins_read_bits", "fins_read_many", "fins_write_words"):
        fn = getattr(fins_tools, name)
        assert getattr(fn, "_is_governed_tool", False), f"{name} is not governed"


@pytest.mark.unit
def test_fins_undo_descriptor_restores_before():
    from mcp_server.tools.fins_tools import _fins_undo

    params = {"endpoint": "omron1", "area": "DM", "address": 100}
    result = {"applied": True, "before": [10, 20]}
    undo = _fins_undo(params, result)
    assert undo is not None
    assert undo["tool"] == "fins_write_words"
    assert undo["params"]["values"] == [10, 20]
    assert undo["params"]["dry_run"] is False
    assert undo["params"]["area"] == "DM" and undo["params"]["address"] == 100


@pytest.mark.unit
def test_fins_undo_skips_dry_run_and_missing_before():
    from mcp_server.tools.fins_tools import _fins_undo

    assert _fins_undo({}, {"applied": False}) is None
    assert _fins_undo({}, {"applied": True, "before": None}) is None
