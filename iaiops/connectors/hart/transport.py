"""HART-IP wire transport over UDP (待核实, read path only).

HART-IP frames a native HART PDU inside an 8-byte HART-IP header and exchanges it
with a HART-IP server/gateway on UDP/TCP 5094. A session is initiated, then each
HART command is sent as a *token-passing PDU* message and the response read back.

This module is **待核实** — the header layout below follows the public HART-IP
spec structure, but it is NOT verified against a live HART-IP server/gateway here.
The framing is written as pure functions (structurally unit-tested) and the I/O is
isolated in :class:`HartIpSession`, so the codec/ops layers stay testable. The
``_build_hart_ip_client`` factory is module-level so tests monkeypatch it.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from iaiops.core.runtime.connection import OTConnectionError

HART_IP_VERSION = 1
# message_type
MT_REQUEST = 0
MT_RESPONSE = 1
# message_id
MID_SESSION_INITIATE = 0
MID_SESSION_CLOSE = 1
MID_KEEP_ALIVE = 2
MID_TOKEN_PASSING = 3

_HEADER = struct.Struct(">BBBBHH")  # version, type, id, status, seq(2), byte_count(2)
HEADER_LEN = _HEADER.size  # 8


def frame_message(message_type: int, message_id: int, sequence: int,
                  payload: bytes = b"") -> bytes:
    """Build a HART-IP message (8-byte header + payload). Pure / structurally testable."""
    byte_count = HEADER_LEN + len(payload)
    header = _HEADER.pack(
        HART_IP_VERSION, message_type & 0xFF, message_id & 0xFF, 0,
        sequence & 0xFFFF, byte_count & 0xFFFF,
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

    def _exchange(self, message_id: int, payload: bytes) -> bytes:
        self._seq = (self._seq + 1) & 0xFFFF
        self._sock.sendto(
            frame_message(MT_REQUEST, message_id, self._seq, payload),
            (self._host, self._port),
        )
        data, _ = self._sock.recvfrom(65535)
        return data

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


def _build_hart_ip_client(target: Any) -> HartIpSession:
    """Construct (not open) a HART-IP session for ``target`` (待核实, monkeypatchable)."""
    try:
        import hart_protocol  # noqa: F401 — codec lib presence check
    except ImportError as exc:  # pragma: no cover — only without the extra
        raise OTConnectionError(
            "The 'hart-protocol' package is not installed. HART-IP is an OPTIONAL "
            "extra: 'pip install iaiops[hart]'.",
            endpoint=getattr(target, "name", "?"), protocol="hart",
        ) from exc
    if not target.host:
        raise OTConnectionError(
            f"HART-IP endpoint '{target.name}' has no host. Add 'host: <ip>' (HART-IP "
            f"server/gateway; port defaults to 5094) to its config entry.",
            endpoint=getattr(target, "name", "?"), protocol="hart",
        )
    return HartIpSession(target.host, target.port or 5094)


@contextmanager
def hart_session(target: Any) -> Iterator[HartIpSession]:
    """Open a HART-IP session, yield it, always close (translates failures)."""
    if target.protocol != "hart":
        raise OTConnectionError(
            f"Endpoint '{target.name}' is protocol '{target.protocol}', not hart.",
            endpoint=target.name, protocol=target.protocol,
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
            endpoint=target.host, protocol="hart",
        ) from exc
    finally:
        session.close()


__all__ = [
    "frame_message", "parse_message", "session_initiate_payload",
    "HartIpSession", "hart_session",
]
