"""Where an exported program names a field address — per dialect, cited.

What each export can actually tell us, which decides what can be joined later:

* **AWL / STL** — absolute operands (``M 10.0``, ``DB10.DBW 4``, ``PIW 256``,
  ``T 5``) on every statement line, plus quoted symbols (``"Motor_Start"``)
  whose address lives in the symbol table, which is not part of the export.
* **Siemens SCL (.scl)** — IEC-style absolute operands (``%I0.0``, ``%MW20``,
  ``%DB10.DBW4``) where the author wrote them; most TIA code is symbolic
  (``"Line_DB".Speed``) and carries no address at all.
* **Rockwell L5X** — declared controller and program tags. For a Logix
  controller the tag path IS the address the CIP connector reads by.

Indirect access (``DBW [AR1,P#0.0]``, pointers) is recorded as a site that
touches *some* address — never resolved to one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from iaiops.core.brain.plc_program import awl_parser
from iaiops.core.brain.plc_program.addresses import S7Address, parse_s7_program_address
from iaiops.core.brain.plc_program.model import ProgramOutline
from iaiops.core.brain.plc_program.st_parser import _BLOCK_RE, _strip_comments

_MAX_QUOTE = 160
_AWL_SKIP = re.compile(r"^\s*(NETWORK|TITLE|END_|VERSION|BEGIN|AUTHOR|FAMILY|NAME)\b", re.I)
_INDIRECT = re.compile(r"\[\s*(AR[12]|[A-Z]*[WD]\s*\d+|#\w+)", re.I)
_SCL_ADDR = re.compile(
    r"%(DB\d+\.DB[XBWD]\d+(?:\.[0-7])?|P[IEQA][BWD]\d+|[IEQAM][BWD]?\d+(?:\.[0-7])?)"
    r"(:P)?(?![\w.:])",
    re.I,
)
_SCL_QUOTED = re.compile(r'"([^"]+)"\s*\.')
_SCL_VAR = re.compile(r"^\s*VAR", re.I)
_SCL_END_VAR = re.compile(r"^\s*END_VAR\b", re.I)


@dataclass(frozen=True)
class AddressSite:
    """One place the export names an address."""

    address: S7Address
    access: str  # read / write / declare / reference
    block: str
    line: int
    source_line: str


@dataclass(frozen=True)
class SymbolSite:
    """A name whose address is NOT in the export (symbol / tag table)."""

    symbol: str
    block: str
    line: int


@dataclass(frozen=True)
class S7Scan:
    """Everything the S7-dialect scan found."""

    addresses: tuple[AddressSite, ...]
    symbols: tuple[SymbolSite, ...]
    indirect: tuple[tuple[str, int, str], ...]  # (block, line, source_line)


def _quote(raw: str) -> str:
    return raw.strip()[:_MAX_QUOTE]


def scan_awl(text: str) -> S7Scan:
    """Absolute operands, quoted data symbols and indirect sites in AWL text."""
    addresses: list[AddressSite] = []
    symbols: list[SymbolSite] = []
    indirect: list[tuple[str, int, str]] = []
    block = ""
    for idx, raw in enumerate(text.splitlines(), start=1):
        code = awl_parser._COMMENT_RE.sub("", raw)
        header = awl_parser._BLOCK_RE.match(code)
        if header:
            block = header.group(2).strip().strip('"')
            continue
        if not code.strip() or _AWL_SKIP.match(code):
            continue
        access = awl_parser.classify_awl_access(code)
        if _INDIRECT.search(code):
            indirect.append((block, idx, _quote(raw)))
        for token in awl_parser.ADDRESS_RE.findall(code):
            address = parse_s7_program_address(token)
            if address is not None:
                addresses.append(AddressSite(address, access, block, idx, _quote(raw)))
        if access != "call":  # a CALL target is a block, not a data symbol
            for name in awl_parser._SYMBOL_RE.findall(code):
                symbols.append(SymbolSite(name, block, idx))
    return S7Scan(tuple(addresses), tuple(symbols), tuple(indirect))


def _scl_access(code: str, end: int, in_var: bool) -> str:
    if in_var:
        return "declare"
    return "write" if code[end:].lstrip().startswith(":=") else "read"


def scan_scl(text: str) -> S7Scan:
    """``%`` absolute operands and quoted global symbols in Siemens SCL text."""
    code_lines, _comments, _count = _strip_comments(text)
    raw_lines = text.splitlines()
    addresses: list[AddressSite] = []
    symbols: list[SymbolSite] = []
    indirect: list[tuple[str, int, str]] = []
    block, in_var = "", False
    for idx, code in enumerate(code_lines, start=1):
        raw = raw_lines[idx - 1] if idx - 1 < len(raw_lines) else code
        header = _BLOCK_RE.match(code)
        if header:
            block, in_var = header.group(2).strip().strip('"'), False
            continue
        if _SCL_END_VAR.match(code):
            in_var = False
            continue
        if _SCL_VAR.match(code):
            in_var = True
            continue
        if re.search(r"\b(PEEK|POKE)\w*\s*\(", code, re.I):
            indirect.append((block, idx, _quote(raw)))
        for m in _SCL_ADDR.finditer(code):
            # `%IW256:P` reads the peripheral, not the process image.
            token = ("P" + m.group(1)) if m.group(2) else m.group(1)
            address = parse_s7_program_address(token)
            if address is not None:
                access = _scl_access(code, m.end(), in_var)
                addresses.append(AddressSite(address, access, block, idx, _quote(raw)))
        for m in _SCL_QUOTED.finditer(code):
            symbols.append(SymbolSite(m.group(1), block, idx))
    return S7Scan(tuple(addresses), tuple(symbols), tuple(indirect))


@dataclass(frozen=True)
class LogixTag:
    """A declared L5X tag and the CIP path a Logix connector reads it by."""

    name: str
    program: str  # "" for controller scope
    data_type: str
    description: str

    @property
    def path(self) -> str:
        return f"Program:{self.program}.{self.name}" if self.program else self.name

    @property
    def key(self) -> str:
        """Logix tag names are case-insensitive; the comparison is too."""
        return self.path.casefold()


def logix_tags(outline: ProgramOutline) -> tuple[LogixTag, ...]:
    """Controller- and program-scoped tags declared in an L5X outline."""
    tags: list[LogixTag] = []
    for block in outline.blocks:
        if block.kind == "DATA_BLOCK":
            program = ""
        elif block.kind == "PROGRAM":
            program = block.name
        else:
            continue  # AOI parameters are not addressable tags
        for var in block.variables:
            if var.name:
                tags.append(LogixTag(var.name, program, var.var_type, var.comment))
    return tuple(tags)


def logix_ref_key(ref: str) -> tuple[str, bool]:
    """A configured Logix ref → (key of the tag it lives in, is it the whole tag).

    ``Program:Main.RunTmr.ACC`` lives in ``Program:Main.RunTmr``; ``Tank[2]``
    lives in ``Tank``. The member/element is part of that one tag — the same
    memory — so it joins as ``member_of_tag``, never as a near name.
    """
    text = str(ref or "").strip()
    prefix = ""
    rest = text
    if text.casefold().startswith("program:"):
        head, _, rest = text[len("program:") :].partition(".")
        prefix = f"Program:{head}."
    base = re.split(r"[.\[]", rest, maxsplit=1)[0]
    whole = prefix + base
    return whole.casefold(), whole.casefold() == text.casefold()


__all__ = [
    "AddressSite",
    "LogixTag",
    "S7Scan",
    "SymbolSite",
    "logix_ref_key",
    "logix_tags",
    "scan_awl",
    "scan_scl",
]
