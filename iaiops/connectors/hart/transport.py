"""HART-IP wire transport over UDP or TCP (read path only).

HART-IP frames a native HART PDU inside an 8-byte HART-IP header and exchanges it
with a HART-IP server/gateway on UDP/TCP 5094. A session is initiated, then each
HART command is sent as a *token-passing PDU* message and the response read back.
The same 8-byte framing is used on both transports — :func:`frame_message` /
:func:`parse_message` are transport-agnostic and reused by both sessions.

Honesty: the live-gateway behaviour stays **待核实** (not validated against a real
HART-IP server here). The framing is pure (structurally unit-tested) and the I/O is
isolated in :class:`HartIpSession` (UDP) and :class:`HartIpTcpSession` (TCP). The
TCP path's header-then-body length-delimiting **is** loopback-verified against an
in-process server (see tests). The ``_build_hart_ip_client`` factory is module-level
so tests monkeypatch it, and selects UDP vs TCP from the target's ``transport``.
"""

from __future__ import annotations

import socket
import struct
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from iaiops.core.runtime.connection import OTConnectionError

HART_IP_VERSION = 1
# message_type
MT_REQUEST = 0
MT_RESPONSE = 1
MT_PUBLISH = 2  # unsolicited burst publish from the gateway/device
# message_id
MID_SESSION_INITIATE = 0
MID_SESSION_CLOSE = 1
MID_KEEP_ALIVE = 2
MID_TOKEN_PASSING = 3

_HEADER = struct.Struct(">BBBBHH")  # version, type, id, status, seq(2), byte_count(2)
HEADER_LEN = _HEADER.size  # 8


def frame_message(message_type: int, message_id: int, sequence: int, payload: bytes = b"") -> bytes:
    """Build a HART-IP message (8-byte header + payload). Pure / structurally testable."""
    byte_count = HEADER_LEN + len(payload)
    header = _HEADER.pack(
        HART_IP_VERSION,
        message_type & 0xFF,
        message_id & 0xFF,
        0,
        sequence & 0xFFFF,
        byte_count & 0xFFFF,
    )
    return header + payload


def parse_message(data: bytes) -> dict:
    """Parse a HART-IP message into its header fields + payload. Pure."""
    if len(data) < HEADER_LEN:
        raise ValueError(f"HART-IP message too short ({len(data)} < {HEADER_LEN} bytes)")
    version, mtype, mid, status, seq, byte_count = _HEADER.unpack(data[:HEADER_LEN])
    return {
        "version": version,
        "message_type": mtype,
        "message_id": mid,
        "status": status,
        "sequence": seq,
        "byte_count": byte_count,
        "payload": data[HEADER_LEN:],
    }


def session_initiate_payload(inactivity_close_s: int = 30) -> bytes:
    """Session-Initiate payload: master type (1=primary) + inactivity timeout (ms)."""
    return struct.pack(">BI", 1, max(0, int(inactivity_close_s)) * 1000)


# How many unsolicited/mismatched messages a TCP exchange will skip (keep-alives,
# burst publishes) before concluding the stream is flooded or out of sync.
_MAX_UNMATCHED_TCP_MESSAGES = 8


def _is_matching_response(parsed: dict, message_id: int, sequence: int) -> bool:
    """True when a parsed HART-IP message answers THIS request.

    A response must echo the request's message id and sequence number and carry
    the response type — anything else (a stale answer to an earlier request, a
    keep-alive, an unsolicited publish) is NOT the current response and must not
    be handed to the HART codec (same policy as the FINS SID match).
    """
    return (
        parsed["message_type"] == MT_RESPONSE
        and parsed["message_id"] == message_id
        and parsed["sequence"] == sequence
    )


def _raise_for_status(parsed: dict, host: str, port: int) -> None:
    """Surface a non-zero HART-IP header status as a real error.

    A session/error reply usually carries an EMPTY body; parsing that as a HART
    PDU would silently read as 'device/gateway unreachable' instead of the real
    reason the server rejected the request.
    """
    status = parsed["status"]
    if status != 0:
        raise OTConnectionError(
            f"HART-IP server {host}:{port} answered message_id="
            f"{parsed['message_id']} with error status {status} (0 = success): "
            f"the server rejected the session/request — this is a protocol-level "
            f"refusal, not an unreachable device.",
            endpoint=host,
            protocol="hart",
        )


class HartIpSession:
    """UDP HART-IP session (待核实). Sends token-passing PDUs and reads responses."""

    def __init__(self, host: str, port: int, timeout_s: float = 5.0) -> None:
        self._host = host
        self._port = int(port or 5094)
        self._timeout = timeout_s
        self._sock: Any = None
        self._seq = 0

    def open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self._timeout)
        self._exchange(MID_SESSION_INITIATE, session_initiate_payload())

    def send_hart_pdu(self, pdu: bytes) -> bytes:
        """Send a HART command PDU as a token-passing message; return the HART response bytes."""
        resp = self._exchange(MID_TOKEN_PASSING, pdu)
        return parse_message(resp)["payload"]

    def receive_message(self, timeout_s: float) -> dict | None:
        """Read ONE incoming HART-IP datagram, or None on timeout (burst listener)."""
        previous = self._sock.gettimeout()
        self._sock.settimeout(max(0.05, float(timeout_s)))
        try:
            data, _ = self._sock.recvfrom(65535)
            return parse_message(data)
        except TimeoutError:
            return None
        finally:
            self._sock.settimeout(previous)

    def _exchange(self, message_id: int, payload: bytes) -> bytes:
        self._seq = (self._seq + 1) & 0xFFFF
        self._sock.sendto(
            frame_message(MT_REQUEST, message_id, self._seq, payload),
            (self._host, self._port),
        )
        return self._read_matching_response(message_id)

    def _read_matching_response(self, message_id: int) -> bytes:
        """Read datagrams until one answers THIS request, or the deadline passes.

        UDP delivers whatever arrives: a stale response to an earlier request, a
        keep-alive, a foreign/runt datagram. None of those is the current
        response — mismatches are discarded and reading continues until the
        matching type/id/sequence shows up or the timeout is spent.
        """
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._no_matching_response_error(message_id)
            self._sock.settimeout(remaining)
            try:
                data, _ = self._sock.recvfrom(65535)
            except TimeoutError as exc:  # socket.timeout is TimeoutError (3.10+)
                raise self._no_matching_response_error(message_id) from exc
            try:
                parsed = parse_message(data)
            except ValueError:
                continue  # runt/garbage datagram — not HART-IP framing
            if not _is_matching_response(parsed, message_id, self._seq):
                continue  # stale / keep-alive / foreign — keep reading
            _raise_for_status(parsed, self._host, self._port)
            return data

    def _no_matching_response_error(self, message_id: int) -> OTConnectionError:
        return OTConnectionError(
            f"HART-IP {self._host}:{self._port}: no matching response to "
            f"message_id={message_id} seq={self._seq} within {self._timeout}s "
            f"(mismatched/stale datagrams are discarded, never trusted as the "
            f"current response).",
            endpoint=self._host,
            protocol="hart",
        )

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._exchange(MID_SESSION_CLOSE, b"")
            except Exception:  # noqa: BLE001 — best-effort graceful close
                pass
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


class HartIpTcpSession:
    """TCP HART-IP session. Same framing/sequence as UDP, but length-delimited.

    TCP is a byte stream with no message boundaries, so a single ``recv`` may return
    a partial frame OR several frames coalesced. Each response is therefore read by
    first reading the fixed 8-byte header, parsing its ``byte_count``, then reading
    exactly ``byte_count - HEADER_LEN`` more bytes — never relying on one ``recv`` to
    return a whole message. The live-gateway behaviour is 待核实; the framing /
    length-delimiting is loopback-verified.
    """

    def __init__(self, host: str, port: int, timeout_s: float = 5.0) -> None:
        self._host = host
        self._port = int(port or 5094)
        self._timeout = timeout_s
        self._sock: Any = None
        self._seq = 0

    def open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self._timeout)
        self._sock.connect((self._host, self._port))
        self._exchange(MID_SESSION_INITIATE, session_initiate_payload())

    def send_hart_pdu(self, pdu: bytes) -> bytes:
        """Send a HART command PDU as a token-passing message; return the HART response bytes."""
        resp = self._exchange(MID_TOKEN_PASSING, pdu)
        return parse_message(resp)["payload"]

    def receive_message(self, timeout_s: float) -> dict | None:
        """Read ONE incoming HART-IP message (framed), or None on timeout.

        Used by the unsolicited-burst listener: publish messages arrive without a
        matching request, so this bypasses the request/response matcher.
        """
        previous = self._sock.gettimeout()
        self._sock.settimeout(max(0.05, float(timeout_s)))
        try:
            return parse_message(self._read_message())
        except TimeoutError:
            return None
        finally:
            self._sock.settimeout(previous)

    def _exchange(self, message_id: int, payload: bytes) -> bytes:
        self._seq = (self._seq + 1) & 0xFFFF
        self._sock.sendall(frame_message(MT_REQUEST, message_id, self._seq, payload))
        # A HART-IP TCP stream may interleave keep-alives / unsolicited publish
        # messages with responses: skip anything that does not answer THIS
        # request (type/id/sequence), bounded so a flooded stream fails loudly.
        for _ in range(_MAX_UNMATCHED_TCP_MESSAGES):
            data = self._read_message()
            parsed = parse_message(data)
            if _is_matching_response(parsed, message_id, self._seq):
                _raise_for_status(parsed, self._host, self._port)
                return data
        raise OTConnectionError(
            f"HART-IP {self._host}:{self._port}: none of the last "
            f"{_MAX_UNMATCHED_TCP_MESSAGES} messages answered message_id="
            f"{message_id} seq={self._seq} — the stream is flooded with "
            f"unsolicited traffic or out of sync.",
            endpoint=self._host,
            protocol="hart",
        )

    def _read_message(self) -> bytes:
        header = self._recv_exactly(HEADER_LEN)
        byte_count = parse_message(header)["byte_count"]
        body_len = byte_count - HEADER_LEN
        if body_len < 0:
            raise OTConnectionError(
                f"HART-IP TCP framing error: header byte_count {byte_count} < "
                f"{HEADER_LEN} (header length). The peer is not speaking HART-IP framing.",
                endpoint=self._host,
                protocol="hart",
            )
        body = self._recv_exactly(body_len) if body_len else b""
        return header + body

    def _recv_exactly(self, n: int) -> bytes:
        """Read exactly ``n`` bytes from the stream (TCP recv may return fewer)."""
        chunks: list[bytes] = []
        got = 0
        while got < n:
            chunk = self._sock.recv(n - got)
            if not chunk:
                raise OTConnectionError(
                    f"HART-IP TCP connection closed after {got}/{n} bytes — the gateway "
                    f"dropped the connection mid-message.",
                    endpoint=self._host,
                    protocol="hart",
                )
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._exchange(MID_SESSION_CLOSE, b"")
            except Exception:  # noqa: BLE001 — best-effort graceful close
                pass
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


def _wants_tcp(target: Any) -> bool:
    """True when the HART endpoint selects the TCP transport (else UDP, the default)."""
    return str(getattr(target, "transport", "") or "").strip().lower() == "tcp"


def _build_hart_ip_client(target: Any) -> HartIpSession | HartIpTcpSession:
    """Construct (not open) a HART-IP session for ``target`` (monkeypatchable).

    Selects the TCP session when ``target.transport == 'tcp'``, else the UDP session.
    Live-gateway behaviour is 待核实.
    """
    try:
        import hart_protocol  # noqa: F401 — codec lib presence check
    except ImportError as exc:  # pragma: no cover — only without the extra
        raise OTConnectionError(
            "The 'hart-protocol' package is not installed. HART-IP is an OPTIONAL "
            "extra: 'pip install iaiops[hart]'.",
            endpoint=getattr(target, "name", "?"),
            protocol="hart",
        ) from exc
    if not target.host:
        raise OTConnectionError(
            f"HART-IP endpoint '{target.name}' has no host. Add 'host: <ip>' (HART-IP "
            f"server/gateway; port defaults to 5094) to its config entry.",
            endpoint=getattr(target, "name", "?"),
            protocol="hart",
        )
    if _wants_tcp(target):
        return HartIpTcpSession(target.host, target.port or 5094)
    return HartIpSession(target.host, target.port or 5094)


@contextmanager
def hart_session(target: Any) -> Iterator[HartIpSession | HartIpTcpSession]:
    """Open a HART-IP session, yield it, always close (translates failures)."""
    if target.protocol != "hart":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not hart.",
            endpoint=target.name,
            protocol=target.protocol,
        )
    session = _build_hart_ip_client(target)
    try:
        session.open()
        yield session
    except OTConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any I/O failure
        raise OTConnectionError(
            f"HART-IP '{target.name}' ({target.host}:{target.port or 5094}) failed: "
            f"{exc}. The HART-IP wire transport is 待核实 — validate against a live "
            f"HART-IP server/gateway.",
            endpoint=target.host,
            protocol="hart",
        ) from exc
    finally:
        session.close()


__all__ = [
    "frame_message",
    "parse_message",
    "session_initiate_payload",
    "HartIpSession",
    "HartIpTcpSession",
    "hart_session",
]
