"""The PCCC (PLC-5 / SLC-500 / MicroLogix) half of the EtherNet/IP harness.

`eip_plc_harness.py` speaks Logix CIP — symbolic tags, a tag list, connected
messaging. An SLC is a different protocol wearing the same encapsulation: CIP
service **0x4B (Execute PCCC)** on the PCCC object (class 0x67), carrying a DF1
command inside. There is no symbol table; there are numbered data files
(`N7`, `F8`, `B3`, `T4`…) addressed by file number, type code and element.

That is why the `slc` path had stayed mock-only while the Logix path reached
rung 2b: it needed a *second* protocol in the harness, not a second tag.

What a request looks like on the wire, after the CIP header::

    07 <vid:2> <vsn:4>      requestor id (echoed verbatim in the reply)
    CMD STS <TNS:2> FNC     DF1 command header
    <function-specific data>

and the reply is the same requestor id, then ``CMD|0x40``, the status byte, the
echoed transaction id, and the data. Those offsets are not decorative:
`pycomm3.slc_driver` reads the status at a **fixed offset 58** of the raw reply
and the data at **61**, so a byte of drift anywhere before them turns every read
into a parse error rather than a wrong value.

Implemented (what the connector's `slc` ops actually call):

* ``CMD 0x06 / FNC 0x03`` — diagnostic status → the processor-type string, which
  is `eip_controller_info(plctype='slc')` and also what `get_file_directory()`
  reads first to decide the File-0 layout.
* ``CMD 0x0F / FNC 0xA1`` — the File-0 (directory) size read and the sequential
  content reads behind `get_file_directory()`, i.e. `eip_list_tags(plctype='slc')`.
* ``CMD 0x0F / FNC 0xA2`` — protected typed logical read: `eip_read_tag` /
  `eip_read_many`.
* ``CMD 0x0F / FNC 0xAB`` — protected typed logical masked write: `eip_write_tag`.

Anything else answers PCCC status ``0x10`` ("illegal command or format"), which is
how a real SLC refuses — and, unlike the Logix path where pycomm3 rejects unknown
tags client-side, it means the **wire-level error path is reachable here**.
"""

from __future__ import annotations

import struct

# The type string a real SLC 5/05 returns; its first four characters are what
# pycomm3's ``_get_sys0_info`` keys the File-0 layout off (1747 → the 5/05 shape:
# rows of 10 bytes from offset 79, file type 0x01). Exactly 11 characters, because
# that is the slice pycomm3 takes.
PROCESSOR_TYPE = "1747-L553  "

# PCCC file-type codes ↔ letters, and element sizes in bytes (pycomm3's tables).
_TYPE_CODES = {
    0x82: "O",
    0x83: "I",
    0x84: "S",
    0x85: "B",
    0x86: "T",
    0x87: "C",
    0x88: "R",
    0x89: "N",
    0x8A: "F",
}
_CODE_FOR = {letter: code for code, letter in _TYPE_CODES.items()}
_ELEMENT_SIZE = {"O": 2, "I": 2, "S": 2, "B": 2, "T": 6, "C": 6, "R": 6, "N": 2, "F": 4}

#: The data-table layout this virtual SLC reports and serves: file number →
#: (type letter, element count). Standard SLC numbering, so the directory a test
#: asserts is the one an engineer would recognise.
DATA_FILES: dict[int, tuple[str, int]] = {
    0: ("O", 1),
    1: ("I", 1),
    2: ("S", 33),
    3: ("B", 10),
    4: ("T", 10),
    5: ("C", 10),
    6: ("R", 10),
    7: ("N", 20),
    8: ("F", 10),
}

STATUS_OK = 0x00
#: PCCC_ERROR_CODE[16] — "Illegal Command or Format, Address may not exist or not
#: enough elements in data file". What a real SLC answers for a bad address.
STATUS_ILLEGAL = 0x10

_CMD_DIAGNOSTIC = 0x06
_FNC_DIAGNOSTIC_STATUS = 0x03
_CMD_PROTECTED_TYPED = 0x0F
_FNC_READ = 0xA2
_FNC_WRITE = 0xAB
_FNC_FILE0 = 0xA1

# The File-0 "how big is the directory" probe: pycomm3 asks for 4 bytes at word
# element 0x23. The content reads that follow are 0x50-byte chunks at word offsets
# 0, 40, 80…, so the pair (size 4, element 0x23) identifies the probe unambiguously.
_FILE0_SIZE_ELEMENT = 0x23
_FILE0_SIZE_LEN = 0x04
_FILE0_LENGTH = 200
_FILE0_ROW_START = 79  # pycomm3's file_position for the 1747 family
_FILE0_ROW_SIZE = 10


def _seed_values() -> dict[str, bytearray]:
    """The data tables, with distinct values so a wrong element is visible.

    Every file exists at its declared size; only the ones a test reads carry
    meaningful values. Reading the wrong element or the wrong file therefore
    returns zeros rather than something that could pass for the right answer.
    """
    values = {
        f"{letter}{number}": bytearray(_ELEMENT_SIZE[letter] * count)
        for number, (letter, count) in DATA_FILES.items()
    }
    # N7: signed 16-bit integers, including a negative one (an unsigned decode
    # would return 65531 and look plausible).
    for element, value in enumerate([1750, 4242, -5, 32767, 100]):
        struct.pack_into("<h", values["N7"], element * 2, value)
    # F8: 32-bit floats.
    for element, value in enumerate([42.5, -0.25]):
        struct.pack_into("<f", values["F8"], element * 4, value)
    # B3:0 — bits 0 and 3 set, so a bit read that ignores the position is wrong.
    struct.pack_into("<H", values["B3"], 0, 0b1001)
    # T4:0 — a timer element is EN/TT/DN flags (word 0), PRE (word 1), ACC (word 2).
    struct.pack_into("<HHH", values["T4"], 0, 0x8000, 500, 137)
    return values


VALUES: dict[str, bytearray] = _seed_values()


def _file0() -> bytes:
    """File 0 — the directory an SLC returns, in the layout pycomm3 parses.

    `_parse_file0` walks rows of 10 bytes from offset 79: a type code, then the
    file's size in bytes as a UINT. The file NUMBER is positional — it increments
    per row — so the rows must appear in order 0..8 for `N7` to be called `N7`.
    """
    data = bytearray(_FILE0_LENGTH)
    data[46] = 8  # ladder files (pycomm3 only prints this)
    data[52] = len(DATA_FILES)  # data files
    for number, (letter, count) in sorted(DATA_FILES.items()):
        offset = _FILE0_ROW_START + number * _FILE0_ROW_SIZE
        data[offset] = _CODE_FOR[letter]
        struct.pack_into("<H", data, offset + 1, _ELEMENT_SIZE[letter] * count)
    return bytes(data)


FILE0 = _file0()


def _file_key(file_number: int, type_code: int) -> str | None:
    """``(7, 0x89)`` → ``"N7"``, or None when this SLC has no such file."""
    letter = _TYPE_CODES.get(type_code)
    if letter is None:
        return None
    declared = DATA_FILES.get(file_number)
    if declared is None or declared[0] != letter:
        return None
    return f"{letter}{file_number}"


def _read(args: bytes) -> tuple[int, bytes]:
    """FNC 0xA2 — protected typed logical read with 3 address fields."""
    size, file_number, type_code, element = args[0], args[1], args[2], args[3]
    key = _file_key(file_number, type_code)
    if key is None:
        return STATUS_ILLEGAL, b""
    start = element * _ELEMENT_SIZE[key[0]]
    table = VALUES[key]
    if start + size > len(table):
        # A real SLC refuses past the end of a data file rather than padding —
        # and this is the branch the Logix path cannot reach, because pycomm3
        # rejects unknown Logix tags client-side.
        return STATUS_ILLEGAL, b""
    return STATUS_OK, bytes(table[start : start + size])


def _write(args: bytes) -> tuple[int, bytes]:
    """FNC 0xAB — protected typed logical masked write.

    The mask is 0xFFFF for a whole-element write and a single bit for a bit
    write; honouring it is what keeps `B3:0/3` from clearing `B3:0/0`.
    """
    size, file_number, type_code, element = args[0], args[1], args[2], args[3]
    key = _file_key(file_number, type_code)
    if key is None:
        return STATUS_ILLEGAL, b""
    mask = struct.unpack_from("<H", args, 5)[0]
    payload = args[7 : 7 + size]
    start = element * _ELEMENT_SIZE[key[0]]
    table = VALUES[key]
    if start + size > len(table) or len(payload) < size:
        return STATUS_ILLEGAL, b""
    if mask == 0xFFFF:
        table[start : start + size] = payload
    else:
        old = struct.unpack_from("<H", table, start)[0]
        new = struct.unpack_from("<H", payload, 0)[0]
        struct.pack_into("<H", table, start, (old & ~mask) | (new & mask))
    return STATUS_OK, b""


def _file0_read(args: bytes) -> tuple[int, bytes]:
    """FNC 0xA1 — the directory size probe, then the sequential content reads."""
    size, file_number, type_code, element = args[0], args[1], args[2], args[3]
    if file_number != 0 or type_code != 0x01:
        return STATUS_ILLEGAL, b""
    if size == _FILE0_SIZE_LEN and element == _FILE0_SIZE_ELEMENT:
        return STATUS_OK, struct.pack("<HH", len(FILE0), 0)
    start = element * 2  # the offset pycomm3 sends counts WORDS, the size BYTES
    return STATUS_OK, FILE0[start : start + size]


def pccc_payload(cip: bytes) -> bytes:
    """Answer one Execute-PCCC request; returns the CIP reply's data field.

    The caller wraps this in the CIP reply header, which is what puts the status
    byte at offset 58 and the data at 61.
    """
    path_words = cip[1]
    body = cip[2 + path_words * 2 :]
    requestor = body[0:7]  # length byte + vendor id + serial, echoed verbatim
    command, _status, transaction = body[7], body[8], body[9:11]
    function = body[11]
    args = body[12:]

    if command == _CMD_DIAGNOSTIC and function == _FNC_DIAGNOSTIC_STATUS:
        # pycomm3 slices the type out of data[5:16]; the leading five bytes are a
        # real SLC's mode/status flags, which nothing here reads.
        status, data = STATUS_OK, bytes(5) + PROCESSOR_TYPE.encode("ascii")
    elif command == _CMD_PROTECTED_TYPED and function == _FNC_READ:
        status, data = _read(args)
    elif command == _CMD_PROTECTED_TYPED and function == _FNC_WRITE:
        status, data = _write(args)
    elif command == _CMD_PROTECTED_TYPED and function == _FNC_FILE0:
        status, data = _file0_read(args)
    else:
        status, data = STATUS_ILLEGAL, b""

    return requestor + bytes([command | 0x40, status]) + transaction + data


__all__ = ["DATA_FILES", "PROCESSOR_TYPE", "VALUES", "pccc_payload"]
