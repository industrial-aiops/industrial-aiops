"""A minimal MELSEC MC-protocol (SLMP 3E, binary) PLC, for the live MC test.

**Read the evidence level before trusting this.** Every other live test in this
repo puts a *third-party* server on the far end — a real pymodbus, bacpypes3,
mosquitto, opendnp3. ``pymcprotocol`` ships **no server**, so this file is one:
written from the 3E binary frame layout, not from an independent implementation.

That asymmetry matters and is not hidden: if I misread the spec, this server and
the test's expectations are wrong *together*. What it still buys, and what a mock
cannot:

* **pymcprotocol's real parser is the judge.** The connector's client is the
  genuine library, and it decodes every byte here. A malformed frame — wrong
  subheader, wrong length field, status in the wrong place — makes the real client
  fail, not a stub agree with me.
* **the request is decoded, not ignored.** A mock cannot tell "read D100" from
  "read M0"; this server parses the device code and address out of the frame, so
  asking for the wrong device returns the wrong bank.

So: stronger than a mock, weaker than the ten protocols with a real counterparty.
Recorded as such in the connector docs. Physical PLC remains 待核实 regardless.

Frame layout implemented (binary 3E, Q series — the connector's default)::

    request                                  response
    [0:2]   0x5000 (big endian)              [0:2]   0xD000 (big endian)
    [2]     network                          [2]     network
    [3]     pc                               [3]     pc
    [4:6]   dest_moduleio  (LE)              [4:6]   dest_moduleio (LE)
    [6]     dest_modulesta                   [6]     dest_modulesta
    [7:9]   length = 2 + len(request)  (LE)  [7:9]   length = 2 + len(data) (LE)
    [9:11]  timer (LE)                       [9:11]  end code (LE, 0 = OK)
    [11:13] command (LE)                     [11:]   data
    [13:15] subcommand (LE)
    [15:]   payload

The two index constants the client asserts on — status at 9, data at 11 — come
from ``pymcprotocol``'s own ``_get_answerstatus_index`` / ``_get_answerdata_index``.

Usage::

    python tests/mc_plc_harness.py <port>

Prints ``READY`` once listening, then serves until killed.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import sys

# Device code → the seeded bank. Q-series binary codes, from pymcprotocol's
# DeviceConstants: D=0xA8 (word), M=0x90 (bit).
DEVICE_D = 0xA8
DEVICE_M = 0x90

# Seeded banks, addressed by device number. Distinct ramps so reading the wrong
# device — or the wrong offset — is visible rather than plausible.
WORDS: dict[int, int] = {addr: 1000 + addr for addr in range(200)}
WORDS[100] = 4242  # a landmark inside the window the tests read
WORDS[101] = -7  # negative: the client decodes words as SIGNED
BITS: dict[int, bool] = {addr: addr % 3 == 0 for addr in range(64)}

CPU_TYPE = "Q06UDVCPU"
CPU_CODE = 0x0263

END_CODE_OK = 0x0000
END_CODE_DEVICE_UNSUPPORTED = 0xC059  # what a real CPU answers for a bad request

_SUBHEADER_RESPONSE = 0xD000


def _device(payload: bytes, offset: int) -> tuple[int, int]:
    """Decode one Q-series device spec: 3-byte little-endian number + 1-byte code."""
    number = int.from_bytes(payload[offset : offset + 3], "little")
    code = payload[offset + 3]
    return number, code


def _response(data: bytes, end_code: int = END_CODE_OK) -> bytes:
    return (
        _SUBHEADER_RESPONSE.to_bytes(2, "big")
        + bytes([0x00, 0xFF])  # network, pc
        + struct.pack("<H", 0x03FF)  # dest_moduleio
        + bytes([0x00])  # dest_modulesta
        + struct.pack("<H", 2 + len(data))
        + struct.pack("<H", end_code)
        + data
    )


def _handle(request: bytes) -> bytes:
    """Turn one 3E request into one 3E response."""
    if len(request) < 15 or request[0:2] != b"\x50\x00":
        return _response(b"", END_CODE_DEVICE_UNSUPPORTED)

    command = struct.unpack_from("<H", request, 11)[0]
    subcommand = struct.unpack_from("<H", request, 13)[0]
    payload = request[15:]

    if command == 0x0101:  # read CPU type
        return _response(CPU_TYPE.ljust(16).encode("ascii") + struct.pack("<H", CPU_CODE))

    if command == 0x0401:  # batch read
        number, code = _device(payload, 0)
        size = struct.unpack_from("<H", payload, 4)[0]
        if subcommand == 0x0000:  # word units
            if code != DEVICE_D:
                return _response(b"", END_CODE_DEVICE_UNSUPPORTED)
            data = b"".join(struct.pack("<h", WORDS.get(number + i, 0)) for i in range(size))
            return _response(data)
        if subcommand == 0x0001:  # bit units — two bits per byte, high nibble first
            if code != DEVICE_M:
                return _response(b"", END_CODE_DEVICE_UNSUPPORTED)
            packed = bytearray((size + 1) // 2)
            for i in range(size):
                if BITS.get(number + i, False):
                    packed[i // 2] |= 1 << (4 if i % 2 == 0 else 0)
            return _response(bytes(packed))
        return _response(b"", END_CODE_DEVICE_UNSUPPORTED)

    if command == 0x0403:  # random read
        word_count, dword_count = payload[0], payload[1]
        offset = 2
        data = b""
        for _ in range(word_count):
            number, _code = _device(payload, offset)
            offset += 4
            data += struct.pack("<h", WORDS.get(number, 0))
        for _ in range(dword_count):
            number, _code = _device(payload, offset)
            offset += 4
            low = WORDS.get(number, 0) & 0xFFFF
            high = WORDS.get(number + 1, 0) & 0xFFFF
            data += struct.pack("<i", (high << 16) | low)
        return _response(data)

    if command == 0x1401:  # batch write (word units)
        number, code = _device(payload, 0)
        size = struct.unpack_from("<H", payload, 4)[0]
        for i in range(size):
            WORDS[number + i] = struct.unpack_from("<h", payload, 6 + i * 2)[0]
        return _response(b"")

    return _response(b"", END_CODE_DEVICE_UNSUPPORTED)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        conn: socket.socket = self.request
        while True:
            request = conn.recv(4096)
            if not request:
                return
            conn.sendall(_handle(request))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(port: int) -> None:
    with _Server(("127.0.0.1", port), _Handler) as server:
        print("READY", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]))
