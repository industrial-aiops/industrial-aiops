"""A minimal S7comm PLC (ISO-TSAP / RFC1006), for the live S7 test.

**Same evidence caveat as ``mc_plc_harness.py``, and it applies just as hard.**
``pyS7`` ships no server, so this far end is written by us from the frame layout
rather than being an independent implementation. If we misread S7comm, harness and
expectations are wrong together. What it buys over a mock:

* ``pyS7``'s **real parser** validates every response — TPKT version and length,
  COTP length, the S7 header, the per-item return codes and transport sizes. A
  malformed frame fails against the library, not against a stub that agrees with us;
* the harness **decodes the request**, so DB number, area code, byte offset and
  length all select what comes back. A mock cannot tell ``DB1,INT0`` from
  ``DB2,INT10``.

Three exchanges are implemented, in the order ``pyS7``'s ``connect()`` drives them:

1. **COTP Connection Request → Connection Confirm.** The client checks the TPKT
   version, that the TPKT length matches the buffer, and that the COTP length
   matches the remainder (``ConnectionResponse.parse``).
2. **S7 Communication Setup (PDU negotiation).** The client reads
   ``>HHH`` at offset **21** for (max jobs calling, max jobs called, PDU size).
3. **Read Var (function 0x04).** Per requested tag the response carries a return
   code, transport size, bit-length, then the data — read back at
   ``READ_RES_OVERHEAD`` (= 21) by ``parse_read_response``.

Frame skeleton shared by (2) and (3)::

    [0:4]   TPKT   03 00 <length:2 BE>
    [4:7]   COTP   02 f0 80
    [7]     S7 protocol id 0x32
    [8]     message type (0x03 = ACK_DATA)
    [9:11]  reserved
    [11:13] PDU reference
    [13:15] parameter length (BE)
    [15:17] data length (BE)
    [17:19] error class / error code   ← ACK_DATA only
    [19:]   parameter, then data

Usage::

    python tests/s7_plc_harness.py <port>

Prints ``READY`` once listening, then serves until killed.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import sys

# Seeded DB contents, keyed by DB number → raw bytes. Addressed by byte offset,
# exactly as S7 does. DB1 holds a landmark layout the tests assert on:
#
#   byte 0..1   INT   4242
#   byte 2..3   INT   -7          (signed decode must not read 65529)
#   byte 4..7   REAL  42.5
#   byte 8      BYTE  0xA5        (bit 0 = 1, bit 1 = 0, bit 2 = 1 …)
#   byte 10..11 INT   1000        (a second landmark, further in)
DB1 = bytearray(64)
struct.pack_into(">h", DB1, 0, 4242)
struct.pack_into(">h", DB1, 2, -7)
struct.pack_into(">f", DB1, 4, 42.5)
DB1[8] = 0xA5
struct.pack_into(">h", DB1, 10, 1000)

# DB2 is a different ramp, so reading the wrong DB is visible rather than plausible.
DB2 = bytearray(64)
for i in range(0, 64, 2):
    struct.pack_into(">h", DB2, i, 9000 + i)

DBS: dict[int, bytearray] = {1: DB1, 2: DB2}

# Merker (flag) area, for the non-DB read path.
MERKER = bytearray(64)
struct.pack_into(">h", MERKER, 0, 777)

AREA_MERKER = 0x83
AREA_DB = 0x84

RETURN_CODE_SUCCESS = 0xFF
RETURN_CODE_OUT_OF_RANGE = 0x05  # what a real CPU answers for an absent DB/address
TRANSPORT_SIZE_BYTE_WORD_DWORD = 0x04  # length that follows is in BITS

NEGOTIATED_PDU = 480
MAX_JOBS = 1


def _tpkt(payload: bytes) -> bytes:
    return b"\x03\x00" + struct.pack(">H", len(payload) + 4) + payload


def _connection_confirm(request: bytes) -> bytes:
    """COTP CC echoing the client's source reference as our destination reference."""
    source_reference = struct.unpack_from(">H", request, 6)[0] if len(request) >= 8 else 0
    cotp = (
        b"\xd0"  # PDU type: Connection Confirm
        + struct.pack(">H", 0x0001)  # destination reference (ours)
        + struct.pack(">H", source_reference)  # source reference (theirs, echoed)
        + b"\x00"  # class / options
        # Parameters: TPDU size, then the two TSAPs echoed back.
        + b"\xc0\x01\x0a"
        + b"\xc1\x02\x01\x00"
        + b"\xc2\x02\x01\x02"
    )
    return _tpkt(bytes([len(cotp)]) + cotp)


def _s7_ack(parameter: bytes, data: bytes = b"") -> bytes:
    header = (
        b"\x32\x03"  # protocol id, message type ACK_DATA
        + b"\x00\x00"  # reserved
        + b"\x00\x00"  # PDU reference
        + struct.pack(">H", len(parameter))
        + struct.pack(">H", len(data))
        + b"\x00\x00"  # error class, error code
    )
    return _tpkt(b"\x02\xf0\x80" + header + parameter + data)


def _pdu_negotiation_ack() -> bytes:
    """The client unpacks ``>HHH`` at offset 21 — the three fields after the ACK_DATA
    header (ends at 19) plus the function byte and its reserved byte."""
    parameter = (
        b"\xf0\x00"  # function 0xF0 (setup communication), reserved
        + struct.pack(">H", MAX_JOBS)
        + struct.pack(">H", MAX_JOBS)
        + struct.pack(">H", NEGOTIATED_PDU)
    )
    return _s7_ack(parameter)


def _bank(area: int, db_number: int) -> bytearray | None:
    if area == AREA_DB:
        return DBS.get(db_number)
    if area == AREA_MERKER:
        return MERKER
    return None


def _read_var_ack(request: bytes) -> bytes:
    """Serve function 0x04 (Read Var) from the seeded banks."""
    parameter_length = struct.unpack_from(">H", request, 13)[0]
    # A REQUEST header is 10 bytes (no error class/code), so its parameter starts at
    # 4 + 3 + 10 = 17. An ACK_DATA header is 12 bytes, so a RESPONSE parameter starts
    # at 19. Using 19 for both is what made the first version answer every request
    # with the generic stub.
    parameter = request[17 : 17 + parameter_length]
    tag_count = parameter[1]

    items = b""
    offset = 2  # past function byte + tag count
    for index in range(tag_count):
        # 12 bytes: 12 | 0a | 10 | transport:1 | length:2 | db:2 | area:1 | address:3
        spec = parameter[offset : offset + 12]
        offset += 12
        transport = spec[3]
        length = struct.unpack_from(">H", spec, 4)[0]
        db_number = struct.unpack_from(">H", spec, 6)[0]
        area = spec[8]
        address_bits = int.from_bytes(spec[9:12], "big")
        start = address_bits // 8
        bit_offset = address_bits % 8

        bank = _bank(area, db_number)
        if bank is None:
            items += bytes([RETURN_CODE_OUT_OF_RANGE, 0x00]) + struct.pack(">H", 0)
            continue

        if transport == 0x01:  # BIT — a non-optimized single-bit read
            # NOT exercised by tests/test_s7_live.py: pyS7 coalesces neighbouring
            # bit tags into ONE byte read (transport 0x02) and extracts the bits
            # client-side, so this branch never runs on that path. Kept because a
            # real CPU must answer it and a future pyS7 change could start using
            # it — but mutating it does not fail any test today, and that is worth
            # knowing before trusting it.
            byte = bank[start] if start < len(bank) else 0
            payload = bytes([1 if byte & (1 << bit_offset) else 0])
        else:
            size = _request_byte_size(transport, length)
            payload = bytes(bank[start : start + size]).ljust(size, b"\x00")

        items += (
            bytes([RETURN_CODE_SUCCESS, TRANSPORT_SIZE_BYTE_WORD_DWORD])
            + struct.pack(">H", len(payload) * 8)
            + payload
        )
        # A fill byte separates items; a real CPU does not append one after the last.
        if len(payload) % 2 and index < tag_count - 1:
            items += b"\x00"

    return _s7_ack(b"\x04" + bytes([tag_count]), items)


def _write_var_ack(request: bytes) -> bytes:
    """Serve function 0x05 (Write Var) into the seeded banks.

    Request layout: the parameter carries the same 12-byte item specs as a read;
    the DATA section then carries, per item, ``00 <transport:1> <bitlength:2>``
    followed by the value bytes. The response is one return code per item, read
    back at ``WRITE_RES_OVERHEAD``.
    """
    parameter_length = struct.unpack_from(">H", request, 13)[0]
    data_length = struct.unpack_from(">H", request, 15)[0]
    parameter = request[17 : 17 + parameter_length]
    data = request[17 + parameter_length : 17 + parameter_length + data_length]
    tag_count = parameter[1]

    codes = b""
    p_offset = 2
    d_offset = 0
    for _ in range(tag_count):
        spec = parameter[p_offset : p_offset + 12]
        p_offset += 12
        transport = spec[3]
        db_number = struct.unpack_from(">H", spec, 6)[0]
        area = spec[8]
        start = int.from_bytes(spec[9:12], "big") // 8

        bit_length = struct.unpack_from(">H", data, d_offset + 2)[0]
        d_offset += 4
        size = 1 if transport == 0x01 else (bit_length + 7) // 8
        payload = data[d_offset : d_offset + size]
        d_offset += size
        if size % 2:  # fill byte between items
            d_offset += 1

        bank = _bank(area, db_number)
        if bank is None or start + size > len(bank):
            codes += bytes([RETURN_CODE_OUT_OF_RANGE])
            continue
        bank[start : start + size] = payload
        codes += bytes([RETURN_CODE_SUCCESS])

    return _s7_ack(b"\x05" + bytes([tag_count]), codes)


# Byte width per S7 data-type code, from pyS7's own ``DataTypeSize``. Getting this
# wrong is silently wrong data, not an error: the first version mapped WORD to 1
# byte and DWORD to 2, so a WORD read of the seeded 4242 came back as 4096 and a
# DWORD read raised "payload too short". Both went unnoticed because the tests only
# used INT/REAL/BIT.
_WIDTH_BY_TRANSPORT = {
    0x01: 1,  # BIT
    0x02: 1,  # BYTE / USINT / SINT (pyS7 sends BYTE's code for the latter two)
    0x03: 1,  # CHAR
    0x04: 2,  # WORD — see the ambiguity note below
    0x05: 2,  # INT
    0x06: 4,  # DWORD
    0x07: 4,  # DINT
    0x08: 4,  # REAL
}

# Transport 0x04 is AMBIGUOUS on the wire: pyS7 sends it for WORD with an ELEMENT
# count, and also for LREAL / STRING / WSTRING with a BYTE count
# (requests.py:247-255). One code, two meanings, nothing in the request to tell them
# apart.
#
# Resolved as WORD here, and that is safe in the only direction that matters: an
# LREAL request then **over**-reads (8 bytes wanted, 16 returned) and pyS7 takes the
# 8 it needs, so the value is correct. **Under**-reading is what silently corrupts
# data — which is what the old width table did to WORD. ``test_s7_live.py`` asserts
# the LREAL value rather than leaving this to reasoning.


def _request_byte_size(transport: int, length: int) -> int:
    """Byte width of a requested item: element count x the type's width."""
    return length * _WIDTH_BY_TRANSPORT.get(transport, 1)


def _handle(request: bytes) -> bytes:
    if len(request) < 6:
        return b""
    cotp_pdu_type = request[5]
    if cotp_pdu_type == 0xE0:  # COTP Connection Request
        return _connection_confirm(request)
    if len(request) < 18 or request[7] != 0x32:
        return b""
    function = request[17]  # request parameter start — see _read_var_ack
    if function == 0xF0:  # setup communication
        return _pdu_negotiation_ack()
    if function == 0x04:  # read var
        return _read_var_ack(request)
    if function == 0x05:  # write var
        return _write_var_ack(request)
    return _s7_ack(bytes([function, 0x00]))


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        conn: socket.socket = self.request
        while True:
            request = conn.recv(4096)
            if not request:
                return
            response = _handle(request)
            if response:
                conn.sendall(response)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(port: int) -> None:
    with _Server(("127.0.0.1", port), _Handler) as server:
        print("READY", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]))
