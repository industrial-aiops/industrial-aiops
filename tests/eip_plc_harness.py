"""A minimal EtherNet/IP + CIP PLC (ControlLogix-flavoured), for the live EIP test.

**Same evidence caveat as the MC and S7 harnesses.** ``pycomm3`` ships no server,
so this far end is written by us from the EtherNet/IP encapsulation and CIP
layouts, not from an independent implementation. Misread them and harness and
expectations are wrong together. What it buys over a mock: pycomm3's **real
driver** performs the whole session dance and parses every reply, and the harness
**decodes the request** — the symbolic segment names the tag, so asking for a
different tag returns different data.

Layers implemented, in the order ``LogixDriver.open()`` drives them:

1. **RegisterSession** (encapsulation command ``0x0065``) → a session handle.
2. **ListIdentity** (``0x0063``) → one CPF identity item.
3. **SendRRData** (``0x006F``) carrying CIP, unwrapped from an **Unconnected Send**
   (service ``0x52`` via the Connection Manager) when present:
   * ``Get_Attributes_All`` on the **Identity** object (class ``0x01``) — vendor,
     device type, product code, revision, status, serial, product name;
   * ``Get_Attribute_List`` on the **Controller Info** object (class ``0xAC``) —
     what pycomm3 reads to learn the program type/revision;
   * ``Read Tag`` (service ``0x4C``) with an ANSI symbolic segment → the seeded
     value, typed with its CIP data-type code;
   * ``Write Tag`` (service ``0x4D``) → stores into the same bank.

Encapsulation header (24 bytes, little-endian)::

    [0:2]   command      [2:4]  length (payload after the header)
    [4:8]   session      [8:12] status
    [12:20] sender context (echoed)      [20:24] options

Usage::

    python tests/eip_plc_harness.py <port>

Prints ``READY`` once listening, then serves until killed.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import sys

SESSION_HANDLE = 0x11223344

# CIP elementary data types used below.
CIP_DINT = 0x00C4
CIP_REAL = 0x00CA
CIP_INT = 0x00C3

# Seeded tags: name → (cip type, value). Distinct values so reading the wrong tag
# is visible rather than plausible; the negative one catches an unsigned decode.
TAGS: dict[str, tuple[int, object]] = {
    "MotorSpeed": (CIP_DINT, 1750),
    "Setpoint": (CIP_DINT, 4242),
    "Offset": (CIP_INT, -7),
    "Temperature": (CIP_REAL, 42.5),
}

VENDOR_ID = 0x0001  # Rockwell
DEVICE_TYPE = 0x000E  # PLC
PRODUCT_CODE = 0x005D
REVISION = (32, 11)
SERIAL = 0xC0FFEE01
PRODUCT_NAME = "1756-L83E/B"

STATUS_OK = 0x00
STATUS_PATH_DESTINATION_UNKNOWN = 0x05  # what a real CPU answers for a missing tag

# Connection ids handed out by Forward Open. pycomm3 switches to CONNECTED
# messaging (SendUnitData) once the connection is open, so serving Forward Open
# is not optional — refusing it only sends the driver down its fallback path,
# which then also fails.
OT_CONNECTION_ID = 0x0A0B0C0D
TO_CONNECTION_ID = 0x01020304


def _encap(command: int, session: int, payload: bytes, context: bytes) -> bytes:
    return (
        struct.pack("<HHII", command, len(payload), session, 0)
        + context.ljust(8, b"\x00")[:8]
        + struct.pack("<I", 0)
        + payload
    )


def _identity_payload() -> bytes:
    name = PRODUCT_NAME.encode()
    return (
        struct.pack("<HHHH", VENDOR_ID, DEVICE_TYPE, PRODUCT_CODE, (REVISION[0] << 8) | REVISION[1])
        + struct.pack("<HI", 0x0060, SERIAL)
        + bytes([len(name)])
        + name
        + bytes([0x03])  # state: operational
    )


def _list_identity_payload() -> bytes:
    """One CPF item: type 0x000C (identity), socket address, then the identity."""
    sockaddr = struct.pack(">hHI", 1, 44818, 0x7F000001) + b"\x00" * 8
    item = (
        struct.pack("<H", 1)  # protocol version
        + sockaddr
        + _identity_payload()
    )
    return struct.pack("<H", 1) + struct.pack("<HH", 0x000C, len(item)) + item


def _cpf_reply(cip_reply: bytes) -> bytes:
    """Wrap a CIP reply in the CPF structure SendRRData expects."""
    return (
        struct.pack("<IH", 0, 2)  # interface handle, timeout
        + struct.pack("<H", 2)  # item COUNT — omitting this shifts the whole reply
        + struct.pack("<HH", 0x0000, 0)  # null address item
        + struct.pack("<HH", 0x00B2, len(cip_reply))  # unconnected data item
        + cip_reply
    )


def _cip_reply(service: int, status: int, data: bytes = b"") -> bytes:
    return bytes([service | 0x80, 0x00, status, 0x00]) + data


def _unwrap_unconnected_send(cip: bytes) -> bytes:
    """Return the embedded CIP message from an Unconnected Send, else ``cip``."""
    if not cip or cip[0] != 0x52:
        return cip
    path_words = cip[1]
    offset = 2 + path_words * 2 + 2  # past the CM path and the priority/ticks
    embedded_size = struct.unpack_from("<H", cip, offset)[0]
    offset += 2
    return cip[offset : offset + embedded_size]


def _parse_symbolic(cip: bytes) -> tuple[str | None, int]:
    """Extract an ANSI-symbolic tag name from a CIP request; return (name, offset)."""
    path_words = cip[1]
    path = cip[2 : 2 + path_words * 2]
    if len(path) < 2 or path[0] != 0x91:
        return None, 2 + path_words * 2
    length = path[1]
    name = path[2 : 2 + length].decode("ascii", errors="replace")
    return name, 2 + path_words * 2


def _controller_info_reply() -> bytes:
    """Get_Attribute_List on class 0xAC — pycomm3's ``info`` source.

    Reply shape: attribute count, then per attribute (id, status, value).
    """
    payload = struct.pack("<H", 3)
    payload += struct.pack("<HHH", 1, 0, 0x005D)  # program type
    payload += struct.pack("<HHBB", 2, 0, REVISION[0], REVISION[1])  # revision
    name = PRODUCT_NAME.encode()
    payload += struct.pack("<HH", 7, 0) + bytes([len(name)]) + name  # name
    return _cip_reply(0x03, STATUS_OK, payload)


def _handle_cip(cip: bytes) -> bytes:
    cip = _unwrap_unconnected_send(cip)
    if not cip:
        return _cip_reply(0x00, STATUS_PATH_DESTINATION_UNKNOWN)
    service = cip[0]

    if service == 0x0A:  # Multiple Service Packet — what a multi-tag read becomes
        return _multiple_service_reply(service, cip)

    if service == 0x55:  # Get_Instance_Attribute_List on the Symbol object (0x6B)
        return _tag_list_reply(service)

    if service in (0x54, 0x5B):  # Forward Open / Large Forward Open
        return _forward_open_reply(service, cip)

    if service == 0x4E:  # Forward Close
        return _cip_reply(service, STATUS_OK, struct.pack("<HHI", 0, 0, 0) + b"\x00\x00")

    if service in (0x01, 0x03):  # Get_Attributes_All / Get_Attribute_List
        path_words = cip[1]
        path = cip[2 : 2 + path_words * 2]
        class_id = path[1] if len(path) >= 2 and path[0] == 0x20 else 0
        if class_id == 0xAC:
            return _controller_info_reply()
        return _cip_reply(service, STATUS_OK, _identity_payload())

    if service == 0x4C:  # Read Tag
        name, _ = _parse_symbolic(cip)
        entry = TAGS.get(name or "")
        if entry is None:
            return _cip_reply(service, STATUS_PATH_DESTINATION_UNKNOWN)
        cip_type, value = entry
        return _cip_reply(service, STATUS_OK, struct.pack("<H", cip_type) + _pack(cip_type, value))

    if service == 0x4D:  # Write Tag
        name, offset = _parse_symbolic(cip)
        if name not in TAGS:
            return _cip_reply(service, STATUS_PATH_DESTINATION_UNKNOWN)
        cip_type = struct.unpack_from("<H", cip, offset)[0]
        value = _unpack(cip_type, cip[offset + 4 :])
        TAGS[name] = (cip_type, value)
        return _cip_reply(service, STATUS_OK)

    return _cip_reply(service, STATUS_PATH_DESTINATION_UNKNOWN)


def _multiple_service_reply(service: int, cip: bytes) -> bytes:
    """Serve service 0x0A: N embedded requests, N embedded replies.

    Both request and reply carry a count followed by that many 2-byte offsets,
    each relative to the START of the count field, then the payloads themselves.
    """
    path_words = cip[1]
    body = cip[2 + path_words * 2 :]
    count = struct.unpack_from("<H", body, 0)[0]
    offsets = [struct.unpack_from("<H", body, 2 + i * 2)[0] for i in range(count)]

    replies = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < count else len(body)
        replies.append(_handle_cip(body[start:end]))

    header = struct.pack("<H", count)
    cursor = 2 + count * 2
    for reply in replies:
        header += struct.pack("<H", cursor)
        cursor += len(reply)
    return _cip_reply(service, STATUS_OK, header + b"".join(replies))


def _tag_list_reply(service: int) -> bytes:
    """The controller tag list, as ``LogixDriver.open()`` uploads it.

    Per instance, in the order pycomm3's ``_parse_instance_attribute_list`` reads:
    instance id (UDINT), name (UINT length + bytes), symbol type (UINT), symbol
    address, symbol object address, software control, then three array dimensions.
    Status 0 means "that was the last page" — 0x06 would mean "call me again".
    """
    payload = b""
    for instance, (name, (cip_type, _value)) in enumerate(TAGS.items(), start=1):
        encoded = name.encode("ascii")
        payload += struct.pack("<I", instance)
        payload += struct.pack("<H", len(encoded)) + encoded
        payload += struct.pack("<H", cip_type)  # atomic: bit 15 clear
        payload += struct.pack("<III", 0, 0, 0)  # symbol / object address, sw control
        payload += struct.pack("<III", 0, 0, 0)  # dimensions
    return _cip_reply(service, STATUS_OK, payload)


def _forward_open_reply(service: int, cip: bytes) -> bytes:
    """Accept the connection, echoing the originator's identifying triple.

    Reply: O→T id, T→O id, connection serial, originator vendor, originator
    serial, the two APIs, then the application reply size (0 here).
    """
    path_words = cip[1]
    body = cip[2 + path_words * 2 :]
    # priority/ticks(2), O→T id(4), T→O id(4), serial(2), vendor(2), orig serial(4)
    connection_serial, vendor, originator_serial = struct.unpack_from("<HHI", body, 10)
    payload = (
        struct.pack("<II", OT_CONNECTION_ID, TO_CONNECTION_ID)
        + struct.pack("<HHI", connection_serial, vendor, originator_serial)
        + struct.pack("<II", 8000, 8000)  # O→T and T→O actual packet intervals
        + bytes([0x00, 0x00])  # application reply size, reserved
    )
    return _cip_reply(service, STATUS_OK, payload)


def _pack(cip_type: int, value: object) -> bytes:
    if cip_type == CIP_REAL:
        return struct.pack("<f", float(value))  # type: ignore[arg-type]
    if cip_type == CIP_INT:
        return struct.pack("<h", int(value))  # type: ignore[arg-type]
    return struct.pack("<i", int(value))  # type: ignore[arg-type]


def _unpack(cip_type: int, raw: bytes) -> object:
    if cip_type == CIP_REAL:
        return struct.unpack_from("<f", raw)[0]
    if cip_type == CIP_INT:
        return struct.unpack_from("<h", raw)[0]
    return struct.unpack_from("<i", raw)[0]


def _handle(request: bytes) -> bytes:
    if len(request) < 24:
        return b""
    command, length, session = struct.unpack_from("<HHI", request, 0)
    context = request[12:20]
    payload = request[24 : 24 + length]

    if command == 0x0065:  # RegisterSession
        return _encap(command, SESSION_HANDLE, payload[:4] or b"\x01\x00\x00\x00", context)
    if command == 0x0063:  # ListIdentity
        return _encap(command, session, _list_identity_payload(), context)
    if command == 0x006F:  # SendRRData
        # payload: interface handle (4) + timeout (2) + CPF
        item_count = struct.unpack_from("<H", payload, 6)[0]
        offset = 8
        cip = b""
        for _ in range(item_count):
            item_type, item_len = struct.unpack_from("<HH", payload, offset)
            offset += 4
            if item_type == 0x00B2:
                cip = payload[offset : offset + item_len]
            offset += item_len
        return _encap(command, session, _cpf_reply(_handle_cip(cip)), context)
    if command == 0x0070:  # SendUnitData — CONNECTED messaging
        item_count = struct.unpack_from("<H", payload, 6)[0]
        offset = 8
        cip = b""
        sequence = 0
        for _ in range(item_count):
            item_type, item_len = struct.unpack_from("<HH", payload, offset)
            offset += 4
            if item_type == 0x00B1:  # connected data item: seq count, then CIP
                sequence = struct.unpack_from("<H", payload, offset)[0]
                cip = payload[offset + 2 : offset + item_len]
            offset += item_len
        reply = _handle_cip(cip)
        body = (
            struct.pack("<IH", 0, 2)
            + struct.pack("<H", 2)
            + struct.pack("<HHI", 0x00A1, 4, TO_CONNECTION_ID)
            + struct.pack("<HH", 0x00B1, len(reply) + 2)
            + struct.pack("<H", sequence)
            + reply
        )
        return _encap(command, session, body, context)
    if command == 0x0066:  # UnRegisterSession — no reply
        return b""
    return _encap(command, session, b"", context)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        conn: socket.socket = self.request
        while True:
            request = conn.recv(65535)
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
