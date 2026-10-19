"""S7 absolute addresses in one canonical form, from either side of the join.

A program operand (``DB10.DBW 4``, ``M 10.0``, ``%MW20``, German ``E 0.0``) and a
configured S7 point (pyS7 syntax: ``DB10,I4``, ``M10.0``, ``MW20``) name the same
memory when — and only when — area, DB number, start byte, bit and width agree.
That is the whole comparison. It is a normalisation of ONE address space, not a
translation between two: nothing here maps an S7 operand to a Modbus register,
an OPC UA node or a Logix tag, because no such mapping exists in the export.

Width is part of the address on purpose. ``MW20`` and ``MD20`` start at the same
byte but are different reads; calling them a match would join a 16-bit counter
to a 32-bit point. They are reported as an overlap instead (see ``field_xref``).

Strings (``DB102,S10.15``) have no fixed width and are returned as ``None`` —
"not comparable", never a guess at their length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Bytes per width letter in a program operand (X / bare bit = 0).
_PROGRAM_WIDTH = {"X": 0, "B": 1, "W": 2, "D": 4}
#: pyS7 data-type token → bytes (``pyS7.address_parser.TOKEN_TABLE``; strings omitted).
_CONFIG_WIDTH = {
    "X": 0,
    "B": 1,
    "BYTE": 1,
    "C": 1,
    "CHAR": 1,
    "USINT": 1,
    "USI": 1,
    "SINT": 1,
    "SI": 1,
    "I": 2,
    "INT": 2,
    "W": 2,
    "WORD": 2,
    "DI": 4,
    "DINT": 4,
    "DW": 4,
    "DWORD": 4,
    "D": 4,
    "R": 4,
    "REAL": 4,
    "LR": 8,
    "LREAL": 8,
}
#: German mnemonics (E = Eingang, A = Ausgang) name the same areas as I / Q.
_AREA = {"I": "I", "E": "I", "Q": "Q", "A": "Q", "M": "M"}
_WIDTH_SUFFIX = {1: "B", 2: "W", 4: "D"}

_PROG_DB = re.compile(r"^%?DB(\d+)\.DB([XBWD])(\d+)(?:\.([0-7]))?$")
_PROG_AREA = re.compile(r"^%?([IEQAM])([BWD])?(\d+)(?:\.([0-7]))?$")
_PROG_PERIPHERAL = re.compile(r"^%?P([IEQA])([BWD])?(\d+)(?:\.([0-7]))?$")
_PROG_TIMER = re.compile(r"^([TCZ])(\d+)$")
_CFG_DB = re.compile(r"^DB(\d+),([A-Z]+)(\d+)(?:\.(\d+))?$")
_CFG_AREA = re.compile(r"^([IEQAM])([A-Z]+)?(\d+)(?:\.(\d+))?$")


@dataclass(frozen=True)
class S7Address:
    """One S7 memory location: area, DB, start byte, bit, width in bytes (0 = bit)."""

    area: str  # DB / I / Q / M / PI / PQ / T / C
    db: int
    byte: int
    bit: int
    size: int

    @property
    def text(self) -> str:
        """The address as a Step 7 engineer writes it (``DB10.DBW4``, ``M10.0``)."""
        if self.area in ("T", "C"):
            return f"{self.area}{self.byte}"
        if self.area == "DB":
            if self.size == 0:
                return f"DB{self.db}.DBX{self.byte}.{self.bit}"
            suffix = _WIDTH_SUFFIX.get(self.size)
            return f"DB{self.db}.DB{suffix}{self.byte}" if suffix else self._raw()
        if self.size == 0:
            return f"{self.area}{self.byte}.{self.bit}"
        suffix = _WIDTH_SUFFIX.get(self.size)
        return f"{self.area}{suffix}{self.byte}" if suffix else self._raw()

    def _raw(self) -> str:
        db = f"DB{self.db} " if self.area == "DB" else ""
        return f"{db}{self.area} byte {self.byte} ({self.size} bytes)"

    @property
    def span(self) -> tuple[int, int]:
        """Half-open byte range (a bit occupies its byte)."""
        return self.byte, self.byte + max(self.size, 1)

    def overlaps(self, other: S7Address) -> bool:
        """Same memory, some shared byte — but not the same address."""
        if (self.area, self.db) != (other.area, other.db) or self == other:
            return False
        if self.area in ("T", "C"):
            return False
        (a0, a1), (b0, b1) = self.span, other.span
        return a0 < b1 and b0 < a1


def parse_s7_program_address(token: str) -> S7Address | None:
    """A program operand → its address, or ``None`` when it is not a data address.

    Accepts Step 7 / TIA spellings with or without the IEC ``%`` and with the
    spaces AWL exports put between area and offset. A bare ``DB10`` names a
    block (``OPN DB10``), not a location, and is ``None``.
    """
    text = re.sub(r"\s+", "", str(token or "")).upper()
    if m := _PROG_DB.match(text):
        db, width, start, bit = m.groups()
        if width == "X" and bit is None:
            return None
        return S7Address("DB", int(db), int(start), int(bit or 0), _PROGRAM_WIDTH[width])
    if m := _PROG_AREA.match(text):
        area, width, start, bit = m.groups()
        if width is None and bit is None:
            return None  # "M10" is not an S7 operand
        if width is not None and bit is not None:
            return None
        size = _PROGRAM_WIDTH[width] if width else 0
        return S7Address(_AREA[area], 0, int(start), int(bit or 0), size)
    if m := _PROG_PERIPHERAL.match(text):
        area, width, start, bit = m.groups()
        if (width is None) == (bit is None):
            return None
        size = _PROGRAM_WIDTH[width] if width else 0
        return S7Address("P" + _AREA[area], 0, int(start), int(bit or 0), size)
    if m := _PROG_TIMER.match(text):
        kind, number = m.groups()
        return S7Address("T" if kind == "T" else "C", 0, int(number), 0, 0)
    return None


def parse_s7_config_ref(ref: str) -> S7Address | None:
    """A configured pyS7 ref → its address, or ``None`` when not comparable.

    Mirrors ``pyS7.address_parser.map_address_to_tag`` (a test holds the two
    together); strings and anything pyS7 itself would refuse are ``None``.
    """
    text = str(ref or "").strip().upper()
    if m := _CFG_DB.match(text):
        db, token, start, bit = m.groups()
        return _config_address("DB", int(db), token, int(start), bit)
    if m := _CFG_AREA.match(text):
        area, token, start, bit = m.groups()
        return _config_address(_AREA[area], 0, token or "X", int(start), bit)
    return None


def _config_address(
    area: str, db: int, token: str, start: int, bit: str | None
) -> S7Address | None:
    size = _CONFIG_WIDTH.get(token)
    if size is None:
        return None
    if size == 0:
        if bit is None or not 0 <= int(bit) <= 7:
            return None
        return S7Address(area, db, start, int(bit), 0)
    if bit is not None:
        return None
    return S7Address(area, db, start, 0, size)


__all__ = ["S7Address", "parse_s7_config_ref", "parse_s7_program_address"]
