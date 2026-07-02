"""Minimal in-repo Omron FINS client — stdlib ``socket`` only, no third-party lib.

Implements the small FINS command subset iaiops needs, per the Omron FINS
command reference (W227) and the CS/CJ Ethernet Units manual (W342):

  * ``0101`` MEMORY AREA READ    — words or bits from DM/CIO/W/H/A/EM
  * ``0102`` MEMORY AREA WRITE   — words (the ONE write path, MOC-gated upstream)
  * ``0501`` CONTROLLER DATA READ — CPU model / version
  * ``0601`` CONTROLLER STATUS READ — run/stop status, mode, error flags

Transports: FINS/UDP (default port 9600) frames the raw 10-byte FINS header
directly in one datagram; FINS/TCP wraps every FINS frame in a 16-byte
FINS/TCP header after a node-address handshake (client command 0 → server
command 1). Requests carry an incrementing SID; a response whose SID does not
match is REJECTED (no retries — per-call sessions, bounded parsing).

Honesty: framing and command layouts follow the W227/W342 manuals and are
self-tested against the in-repo mock FINS responder (tests/test_fins.py);
behaviour against live Omron PLCs is 待核实 unless noted otherwise.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

FINS_HEADER_LEN = 10
DEFAULT_FINS_PORT = 9600
MAX_RESPONSE_BYTES = 4096  # bounded receive — largest read (500 words) ≈ 1KB + header
DEFAULT_GCT = 0x02  # gateway count per W342 (待核实 for multi-network routing)

# ICF bits: 0x80 = bridge/gateway use, 0x40 = response frame, 0x01 = no response needed.
ICF_COMMAND = 0x80  # command, response required
ICF_RESPONSE_BIT = 0x40

# Command codes (MRC, SRC).
CMD_MEMORY_AREA_READ = (0x01, 0x01)
CMD_MEMORY_AREA_WRITE = (0x01, 0x02)
CMD_CONTROLLER_DATA_READ = (0x05, 0x01)
CMD_CONTROLLER_STATUS_READ = (0x06, 0x01)

# FINS/TCP framing (W342 §7): 'FINS' magic + length + command + error code.
FINS_TCP_MAGIC = b"FINS"
FINS_TCP_HEADER = struct.Struct(">4sIII")  # magic, length, command, error_code
FINS_TCP_CMD_CLIENT_NODE = 0  # client → server: node address data send
FINS_TCP_CMD_SERVER_NODE = 1  # server → client: node address assignment
FINS_TCP_CMD_FINS_FRAME = 2  # either direction: a framed FINS message
FINS_TCP_ERRORS = {  # W342 FINS/TCP error codes (待核实 beyond the common ones)
    0x00000000: "normal",
    0x00000001: "the FINS/TCP header is not 'FINS'",
    0x00000002: "the data length is too long",
    0x00000003: "the command is not supported",
    0x00000020: "all connections are in use",
    0x00000021: "the specified node is already connected",
    0x00000022: "attempt to access a protected node from an unspecified IP",
    0x00000023: "the client FINS node address is out of range",
    0x00000024: "the same FINS node address is being used by client and server",
    0x00000025: "all available node addresses are in use",
}


@dataclass(frozen=True)
class MemoryArea:
    """One addressable FINS memory area (word + bit variant codes, CS/CJ-mode)."""

    name: str
    word_code: int
    bit_code: int  # 0 = bit access not supported here
    max_address: int


# CS/CJ-mode area designation codes per W227/W342. CV-mode codes differ (待核实 /
# unsupported). EM = current bank (0x98); banked EM access (0xA0+bank) 待核实.
MEMORY_AREAS: dict[str, MemoryArea] = {
    "CIO": MemoryArea("CIO", 0xB0, 0x30, 6143),
    "W": MemoryArea("W", 0xB1, 0x31, 511),
    "H": MemoryArea("H", 0xB2, 0x32, 511),
    "A": MemoryArea("A", 0xB3, 0x33, 959),
    "DM": MemoryArea("DM", 0x82, 0x02, 32767),
    "EM": MemoryArea("EM", 0x98, 0x00, 32767),  # current bank; bit access 待核实
}

# FINS end codes (main<<8 | sub), flag bits stripped — common subset per W227 §5 /
# W342 §8 (full table is much larger; unlisted codes print numerically, 待核实).
END_CODES: dict[int, str] = {
    0x0000: "normal completion",
    0x0001: "service canceled",
    0x0101: "local node not in network",
    0x0102: "token timeout",
    0x0103: "retries failed",
    0x0105: "node address range error",
    0x0106: "node address duplication",
    0x0201: "destination node not in network",
    0x0202: "unit missing",
    0x0204: "destination node busy",
    0x0205: "response timeout",
    0x0301: "communications controller error",
    0x0302: "CPU unit error",
    0x0304: "unit number error",
    0x0401: "undefined command",
    0x0402: "not supported by model/version",
    0x0501: "destination address setting error",
    0x0502: "no routing tables",
    0x0503: "routing table error",
    0x0504: "too many relays",
    0x1001: "command too long",
    0x1002: "command too short",
    0x1003: "elements/data don't match",
    0x1004: "command format error",
    0x1005: "header error",
    0x1101: "area classification missing / wrong memory area code",
    0x1102: "access size error",
    0x1103: "address range error",
    0x1104: "address range exceeded",
    0x110B: "response too long",
    0x110C: "parameter error",
    0x2002: "protected",
    0x2003: "table missing",
    0x2004: "data missing",
    0x2101: "read-only area",
    0x2102: "protected (write)",
    0x2103: "cannot register",
    0x2202: "not possible while running",
    0x2203: "wrong PLC mode (PROGRAM)",
    0x2205: "wrong PLC mode (MONITOR)",
    0x2206: "wrong PLC mode (RUN)",
    0x2301: "file device missing",
    0x2302: "memory missing",
    0x3001: "no access right",
    0x4001: "service aborted",
}

# 0601 CONTROLLER STATUS READ decode maps (W227; values beyond these 待核实).
RUN_STATUS = {0x00: "stop", 0x01: "run", 0x80: "cpu_standby"}
RUN_MODES = {0x00: "PROGRAM", 0x02: "MONITOR", 0x04: "RUN"}


class FinsError(Exception):
    """Base error for FINS client failures (framing, end codes, transport)."""


class FinsFramingError(FinsError):
    """The peer's bytes do not parse as the expected FINS frame (or SID mismatch)."""


class FinsEndCodeError(FinsError):
    """The PLC answered with a non-zero FINS end code."""

    def __init__(self, end_code: int, *, relay_error: bool = False,
                 fatal_cpu_error: bool = False, non_fatal_cpu_error: bool = False) -> None:
        self.end_code = end_code
        self.relay_error = relay_error
        self.fatal_cpu_error = fatal_cpu_error
        self.non_fatal_cpu_error = non_fatal_cpu_error
        meaning = END_CODES.get(end_code, "unlisted end code (see Omron W227 §5)")
        flags = "".join(
            f" [{label}]"
            for label, on in (
                ("network relay error", relay_error),
                ("fatal CPU error flag", fatal_cpu_error),
                ("non-fatal CPU error flag", non_fatal_cpu_error),
            )
            if on
        )
        super().__init__(f"FINS end code 0x{end_code:04X}: {meaning}{flags}")


def resolve_area(area: str, *, bit_access: bool = False) -> MemoryArea:
    """Resolve an area name (case-insensitive: DM/CIO/W/H/A/EM) or fail teaching."""
    key = str(area or "").strip().upper()
    found = MEMORY_AREAS.get(key)
    if found is None:
        raise ValueError(
            f"Unknown FINS memory area '{area}'. Supported: "
            f"{', '.join(MEMORY_AREAS)} (CS/CJ-mode codes)."
        )
    if bit_access and not found.bit_code:
        raise ValueError(
            f"FINS area '{found.name}' has no bit-access code here "
            f"(EM bit access 待核实). Use a word read instead."
        )
    return found


def build_fins_frame(
    *,
    sid: int,
    dna: int = 0,
    da1: int = 0,
    da2: int = 0,
    sna: int = 0,
    sa1: int = 0,
    sa2: int = 0,
    gct: int = DEFAULT_GCT,
    command: bytes,
) -> bytes:
    """Build a raw FINS frame: 10-byte header (ICF/RSV/GCT/DNA/DA1/DA2/SNA/SA1/SA2/SID)
    followed by the command bytes (MRC/SRC + parameters). Pure / unit-testable."""
    header = bytes((
        ICF_COMMAND, 0x00, gct & 0xFF,
        dna & 0xFF, da1 & 0xFF, da2 & 0xFF,
        sna & 0xFF, sa1 & 0xFF, sa2 & 0xFF,
        sid & 0xFF,
    ))
    return header + command


def parse_fins_response(data: bytes, *, expect_sid: int, expect_mrc: int,
                        expect_src: int) -> bytes:
    """Validate a FINS response frame; return the payload AFTER the end code.

    Checks (bounded, fail-fast): minimum length, response ICF bit, SID match
    (mismatch = stale/foreign datagram → rejected, retries=0), MRC/SRC echo,
    then the 2-byte end code (flag bits stripped per W342: main bit7 = network
    relay error; sub bits 6/7 = non-fatal/fatal CPU error flags, 待核实).
    """
    if len(data) < FINS_HEADER_LEN + 4:
        raise FinsFramingError(
            f"FINS response too short ({len(data)} bytes < {FINS_HEADER_LEN + 4}). "
            f"The peer is not speaking FINS."
        )
    if len(data) > MAX_RESPONSE_BYTES:
        raise FinsFramingError(
            f"FINS response too long ({len(data)} bytes > {MAX_RESPONSE_BYTES})."
        )
    icf = data[0]
    if not icf & ICF_RESPONSE_BIT:
        raise FinsFramingError(f"FINS frame is not a response (ICF=0x{icf:02X}).")
    sid = data[9]
    if sid != (expect_sid & 0xFF):
        raise FinsFramingError(
            f"FINS SID mismatch: sent {expect_sid & 0xFF}, response carries {sid} "
            f"(stale or foreign frame — rejected, not retried)."
        )
    mrc, src = data[10], data[11]
    if (mrc, src) != (expect_mrc, expect_src):
        raise FinsFramingError(
            f"FINS command echo mismatch: sent {expect_mrc:02X}{expect_src:02X}, "
            f"response says {mrc:02X}{src:02X}."
        )
    main, sub = data[12], data[13]
    end_code = ((main & 0x7F) << 8) | (sub & 0x3F)
    if end_code != 0x0000:
        raise FinsEndCodeError(
            end_code,
            relay_error=bool(main & 0x80),
            fatal_cpu_error=bool(sub & 0x80),
            non_fatal_cpu_error=bool(sub & 0x40),
        )
    return data[FINS_HEADER_LEN + 4:]


def _last_ip_octet(host: str) -> int:
    """Default FINS node number from an IPv4 host's last octet (0 if not IPv4).

    Matches the common 'automatic address conversion' convention on Omron
    Ethernet units (IP last octet == FINS node, 待核实 per-site addressing mode).
    """
    tail = host.rsplit(".", 1)[-1]
    try:
        value = int(tail)
    except ValueError:
        return 0
    return value if 0 <= value <= 254 else 0


class _FinsBase:
    """Shared command builders + response decoding for both transports."""

    _dna: int
    _da1: int
    _da2: int
    _sna: int
    _sa1: int
    _sa2: int
    _sid: int

    def execute(self, command: bytes) -> bytes:  # pragma: no cover — interface
        raise NotImplementedError

    def _next_sid(self) -> int:
        self._sid = (self._sid % 0xFF) + 1  # 1..255, skipping 0
        return self._sid

    # -- command helpers ----------------------------------------------------
    def memory_area_read(self, area_code: int, address: int, bit: int,
                         count: int) -> bytes:
        cmd = bytes(CMD_MEMORY_AREA_READ) + struct.pack(
            ">BHBH", area_code & 0xFF, address & 0xFFFF, bit & 0xFF, count & 0xFFFF
        )
        return self.execute(cmd)

    def memory_area_write(self, area_code: int, address: int, bit: int,
                          data: bytes, count: int) -> bytes:
        cmd = bytes(CMD_MEMORY_AREA_WRITE) + struct.pack(
            ">BHBH", area_code & 0xFF, address & 0xFFFF, bit & 0xFF, count & 0xFFFF
        ) + data
        return self.execute(cmd)

    def read_words(self, area_code: int, address: int, count: int) -> list[int]:
        payload = self.memory_area_read(area_code, address, 0, count)
        if len(payload) < 2 * count:
            raise FinsFramingError(
                f"FINS word-read payload too short: {len(payload)} bytes for "
                f"{count} words."
            )
        return list(struct.unpack(f">{count}H", payload[: 2 * count]))

    def read_bits(self, area_code: int, address: int, bit: int,
                  count: int) -> list[bool]:
        payload = self.memory_area_read(area_code, address, bit, count)
        if len(payload) < count:
            raise FinsFramingError(
                f"FINS bit-read payload too short: {len(payload)} bytes for "
                f"{count} bits."
            )
        return [bool(b & 0x01) for b in payload[:count]]

    def write_words(self, area_code: int, address: int, values: list[int]) -> None:
        data = struct.pack(f">{len(values)}H", *[v & 0xFFFF for v in values])
        self.memory_area_write(area_code, address, 0, data, len(values))

    def controller_data(self) -> dict:
        """0501 CONTROLLER DATA READ → CPU model + version (first 40 bytes).

        The full 0501 response carries more (area sizes, dip switches …) — only
        the model/version block is decoded here; the rest is 待核实.
        """
        payload = self.execute(bytes(CMD_CONTROLLER_DATA_READ))
        model = payload[0:20].split(b"\x00")[0].decode("ascii", "replace").strip()
        version = payload[20:40].split(b"\x00")[0].decode("ascii", "replace").strip()
        return {"model": model, "version": version}

    def controller_status(self) -> dict:
        """0601 CONTROLLER STATUS READ → run status/mode + error flag words."""
        payload = self.execute(bytes(CMD_CONTROLLER_STATUS_READ))
        if len(payload) < 6:
            raise FinsFramingError(
                f"FINS controller-status payload too short ({len(payload)} bytes)."
            )
        status, mode = payload[0], payload[1]
        fatal, non_fatal = struct.unpack(">HH", payload[2:6])
        return {
            "status": RUN_STATUS.get(status, f"unknown(0x{status:02X})"),
            "mode": RUN_MODES.get(mode, f"unknown(0x{mode:02X})"),
            "fatal_error_data": fatal,
            "non_fatal_error_data": non_fatal,
        }


class FinsUdpClient(_FinsBase):
    """FINS/UDP client: one datagram per request/response, SID-matched, no retry."""

    def __init__(self, host: str, port: int = DEFAULT_FINS_PORT, *,
                 da1: int | None = None, sa1: int = 1,
                 timeout_s: float = 10.0) -> None:
        self._host = host
        self._port = int(port or DEFAULT_FINS_PORT)
        self._timeout = float(timeout_s)
        self._sock: socket.socket | None = None
        self._sid = 0
        self._dna = self._da2 = self._sna = self._sa2 = 0
        self._da1 = _last_ip_octet(host) if da1 is None else int(da1)
        self._sa1 = int(sa1)

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self._timeout)

    def execute(self, command: bytes) -> bytes:
        if self._sock is None:
            raise FinsError("FINS/UDP client is not connected (call connect()).")
        sid = self._next_sid()
        frame = build_fins_frame(
            sid=sid, dna=self._dna, da1=self._da1, da2=self._da2,
            sna=self._sna, sa1=self._sa1, sa2=self._sa2, command=command,
        )
        self._sock.sendto(frame, (self._host, self._port))
        data, _addr = self._sock.recvfrom(MAX_RESPONSE_BYTES)
        return parse_fins_response(
            data, expect_sid=sid, expect_mrc=command[0], expect_src=command[1]
        )

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:  # pragma: no cover — close is best-effort
                pass
            self._sock = None


class FinsTcpClient(_FinsBase):
    """FINS/TCP client: node-address handshake, then length-delimited FINS frames.

    Live-PLC behaviour 待核实; the handshake + framing follow W342 §7 and are
    loopback-tested against the in-repo mock responder.
    """

    def __init__(self, host: str, port: int = DEFAULT_FINS_PORT, *,
                 client_node: int = 0, timeout_s: float = 10.0) -> None:
        self._host = host
        self._port = int(port or DEFAULT_FINS_PORT)
        self._timeout = float(timeout_s)
        self._client_node = int(client_node)  # 0 = ask the server to auto-assign
        self._sock: socket.socket | None = None
        self._sid = 0
        self._dna = self._da2 = self._sna = self._sa2 = 0
        self._da1 = 0
        self._sa1 = 0

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self._timeout)
        self._sock.connect((self._host, self._port))
        # Handshake: command 0 (client node address send; 0 = auto-assign) →
        # command 1 response carrying (client node, server node).
        payload = struct.pack(">I", self._client_node & 0xFF)
        self._send_tcp(FINS_TCP_CMD_CLIENT_NODE, payload)
        command, body = self._read_tcp()
        if command != FINS_TCP_CMD_SERVER_NODE or len(body) < 8:
            raise FinsFramingError(
                f"FINS/TCP handshake failed: expected command 1 with 8-byte body, "
                f"got command {command} with {len(body)} bytes."
            )
        client_node, server_node = struct.unpack(">II", body[:8])
        self._sa1 = client_node & 0xFF
        self._da1 = server_node & 0xFF

    def execute(self, command: bytes) -> bytes:
        if self._sock is None:
            raise FinsError("FINS/TCP client is not connected (call connect()).")
        sid = self._next_sid()
        frame = build_fins_frame(
            sid=sid, dna=self._dna, da1=self._da1, da2=self._da2,
            sna=self._sna, sa1=self._sa1, sa2=self._sa2, command=command,
        )
        self._send_tcp(FINS_TCP_CMD_FINS_FRAME, frame)
        tcp_command, body = self._read_tcp()
        if tcp_command != FINS_TCP_CMD_FINS_FRAME:
            raise FinsFramingError(
                f"FINS/TCP peer answered command {tcp_command}, expected "
                f"{FINS_TCP_CMD_FINS_FRAME} (FINS frame)."
            )
        return parse_fins_response(
            body, expect_sid=sid, expect_mrc=command[0], expect_src=command[1]
        )

    def _send_tcp(self, command: int, payload: bytes) -> None:
        # length counts everything AFTER the length field: command+error+payload.
        header = FINS_TCP_HEADER.pack(FINS_TCP_MAGIC, 8 + len(payload), command, 0)
        assert self._sock is not None  # nosec B101 — narrowing for the type checker
        self._sock.sendall(header + payload)

    def _read_tcp(self) -> tuple[int, bytes]:
        header = self._recv_exactly(FINS_TCP_HEADER.size)
        magic, length, command, error_code = FINS_TCP_HEADER.unpack(header)
        if magic != FINS_TCP_MAGIC:
            raise FinsFramingError(
                f"FINS/TCP magic mismatch: {magic!r} — the peer is not speaking "
                f"FINS/TCP framing."
            )
        if error_code != 0:
            meaning = FINS_TCP_ERRORS.get(error_code, "unlisted FINS/TCP error")
            raise FinsError(f"FINS/TCP error 0x{error_code:08X}: {meaning}")
        body_len = int(length) - 8
        if body_len < 0 or body_len > MAX_RESPONSE_BYTES:
            raise FinsFramingError(
                f"FINS/TCP length field out of bounds ({length})."
            )
        body = self._recv_exactly(body_len) if body_len else b""
        return int(command), body

    def _recv_exactly(self, n: int) -> bytes:
        assert self._sock is not None  # nosec B101 — narrowing for the type checker
        chunks: list[bytes] = []
        got = 0
        while got < n:
            chunk = self._sock.recv(n - got)
            if not chunk:
                raise FinsFramingError(
                    f"FINS/TCP connection closed after {got}/{n} bytes."
                )
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:  # pragma: no cover — close is best-effort
                pass
            self._sock = None


__all__ = [
    "CMD_CONTROLLER_DATA_READ",
    "CMD_CONTROLLER_STATUS_READ",
    "CMD_MEMORY_AREA_READ",
    "CMD_MEMORY_AREA_WRITE",
    "DEFAULT_FINS_PORT",
    "END_CODES",
    "FINS_HEADER_LEN",
    "FinsEndCodeError",
    "FinsError",
    "FinsFramingError",
    "FinsTcpClient",
    "FinsUdpClient",
    "MEMORY_AREAS",
    "MemoryArea",
    "build_fins_frame",
    "parse_fins_response",
    "resolve_area",
]
