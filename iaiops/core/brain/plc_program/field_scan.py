"""Where a Siemens export names a field address — AWL and SCL, cited.

What each export can actually tell us, which decides what can be joined later:

* **AWL / STL** — absolute operands (``M 10.0``, ``DB10.DBW 4``, ``PIW 256``,
  ``T 5``) on statement lines, plus quoted symbols (``"Motor_Start"``) whose
  address lives in the symbol table, which is not part of the export.
* **Siemens SCL (.scl)** — IEC-style absolute operands (``%I0.0``, ``%MW20``,
  ``%DB10.DBW4``) where the author wrote them; most TIA code is symbolic
  (``"Line_DB".Speed``) and carries no address at all.

Only OPERAND text is scanned. String literals, comments, quoted symbol names
and ``#local`` variables are blanked first (column-preserving), because
``'check %MW20'`` and ``"Lamp Q 4.0"`` read like addresses and are not — and a
match found inside a string is exactly the plausible wrong answer this refuses.
Declaration sections are skipped (a local named ``IW1`` is not input word 1).

Indirect access is recorded as a site that touches *some* address and is never
resolved to one: register-indirect (``DBW [AR1,P#0.0]``), pointers (``P#M 10.0``
takes an address, it does not access it), and DB-relative operands (``L DBW 4``
after ``OPN DB 10`` — which DB is open is runtime state).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from iaiops.core.brain.plc_program import awl_parser
from iaiops.core.brain.plc_program.addresses import S7Address, parse_s7_program_address
from iaiops.core.brain.plc_program.st_parser import _BLOCK_RE

_MAX_QUOTE = 160
_AWL_SKIP = re.compile(r"^\s*(NETWORK|TITLE|END_|VERSION|BEGIN|AUTHOR|FAMILY|NAME)\b", re.I)
_VAR_START = re.compile(r"^\s*VAR(_\w+)?\b", re.I)
_VAR_END = re.compile(r"^\s*END_VAR\b", re.I)

# Blanked before any operand is looked for. Order = precedence at one position.
# `#name` is a local; `P#…` is a pointer and is kept for the indirect check.
_AWL_NOISE = re.compile(r"//[^\n]*|\"[^\"\n]*\"|'(?:\$.|[^'\n])*'|(?<![Pp])#\w+")
_SCL_NOISE = re.compile(r"//[^\n]*|/\*.*?\*/|\(\*.*?\*\)|'(?:\$.|[^'\n])*'|\"[^\"\n]*\"|#\w+", re.S)
_SCL_COMMENT_OR_STRING = re.compile(r"//[^\n]*|/\*.*?\*/|\(\*.*?\*\)|'(?:\$.|[^'\n])*'", re.S)

_AWL_POINTER = re.compile(r"P#\s*(DB\d+\.DB[XBWD]\s*\d+(?:\.\d+)?|[A-Z]+\s*\d+(?:\.\d+)?)", re.I)
_AWL_DB_RELATIVE = re.compile(r"(?<![\w.])D[BI][XBWD]\s*\d+", re.I)
_AWL_ADDRESS = re.compile(
    r"(?<![\w.#\"'])(DB\d+\.DB[XBWD]\s*\d+(?:\.\d+)?|DB\d+|P[IQEA][WBD]\s*\d+"
    r"|[IQMEA][BWD]?\s*\d+(?:\.\d+)?|[TCZ]\s*\d+)(?![\w.])",
    re.I,
)
# Any bracket left after blanking is register- or memory-indirect (`[AR1,P#0.0]`,
# `[#idx]`, `[MD 10]`) or an array index — an address this scan cannot resolve.
_INDIRECT = re.compile(r"\[")
_DECL_OPEN = re.compile(r"^\s*(TYPE\b|DATA_BLOCK\b)", re.I)
_DECL_CLOSE = re.compile(r"^\s*END_(TYPE|DATA_BLOCK)\b", re.I)
_STRUCT_OPEN = re.compile(r"(?<!END_)\bSTRUCT\b", re.I)
_STRUCT_CLOSE = re.compile(r"\bEND_STRUCT\b", re.I)
_AWL_HEADER_NOISE = re.compile(r"//[^\n]*|'(?:\$.|[^'\n])*'")

_SCL_ADDR = re.compile(
    r"%(DB\d+\.DB[XBWD]\d+(?:\.[0-7])?|P[IEQA][BWD]\d+|[IEQAM][BWD]?\d+(?:\.[0-7])?)"
    r"(:P)?(?![\w.]|:(?!=))",  # `%Q0.0:=` is an assignment, `%IW256:P` a peripheral
    re.I,
)
_SCL_QUOTED = re.compile(r'"([^"\n]+)"\s*\.')
_SCL_PEEK = re.compile(r"\b(PEEK|POKE)\w*\s*\(", re.I)


@dataclass(frozen=True)
class AddressSite:
    """One place the export names an address."""

    address: S7Address
    access: str  # read / write / declare / call / reference
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


def blank(text: str, pattern: re.Pattern[str]) -> str:
    """Replace every match with spaces, keeping newlines (and so line/column)."""
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _awl_line(code: str, raw: str, block: str, idx: int, out: dict) -> None:
    """Collect one AWL statement's operands (``code`` already blanked)."""
    access = awl_parser.classify_awl_access(code)
    if (
        _INDIRECT.search(code)
        or _AWL_POINTER.search(code)
        or _AWL_DB_RELATIVE.search(_AWL_ADDRESS_FULL_DB.sub(" ", code))
    ):
        out["indirect"].append((block, idx, _quote(raw)))
    operands = _AWL_POINTER.sub(lambda m: " " * len(m.group(0)), code)
    for m in _AWL_ADDRESS.finditer(operands):
        address = parse_s7_program_address(m.group(1))
        if address is not None:
            out["addresses"].append(AddressSite(address, access, block, idx, _quote(raw)))


_AWL_ADDRESS_FULL_DB = re.compile(r"DB\d+\.DB[XBWD]\s*\d+", re.I)


class _Declarations:
    """Tracks declaration-only regions: VAR sections, STRUCT bodies, TYPE and DATA_BLOCK.

    A member named ``IW1`` in a DB or UDT is not input word 1, and a DB's initial
    values (``IW1 := 5``) are not statements — none of it is scanned as operands.
    """

    def __init__(self) -> None:
        self.var = False
        self.struct = 0
        self.block = False

    def skip(self, code: str) -> bool:
        """Update the state for one line; True when the line is declaration-only."""
        if _DECL_CLOSE.match(code):
            self.block, self.var, self.struct = False, False, 0
            return True
        if _DECL_OPEN.match(code):
            self.block = True
            return True
        if _VAR_END.match(code):
            self.var = False
            return True
        if _VAR_START.match(code):
            self.var = True
            return True
        if _STRUCT_CLOSE.search(code):
            self.struct = max(0, self.struct - 1)
            return True
        if _STRUCT_OPEN.search(code):
            self.struct += 1
            return True
        return self.var or self.struct > 0 or self.block


def scan_awl(text: str) -> S7Scan:
    """Absolute operands, quoted data symbols and indirect sites in AWL text."""
    out: dict[str, list] = {"addresses": [], "indirect": []}
    symbols: list[SymbolSite] = []
    raw_lines = text.splitlines()
    code_lines = blank(text, _AWL_NOISE).splitlines()
    header_lines = blank(text, _AWL_HEADER_NOISE).splitlines()  # quotes kept for names
    block, decl = "", _Declarations()
    for idx, (raw, code) in enumerate(zip(raw_lines, code_lines, strict=False), start=1):
        header = awl_parser._BLOCK_RE.match(header_lines[idx - 1])
        if header and not _DECL_OPEN.match(code):
            block, decl = header.group(2).strip().strip('"'), _Declarations()
            continue
        if decl.skip(code) or not code.strip() or _AWL_SKIP.match(code):
            continue
        _awl_line(code, raw, block, idx, out)
        stripped = awl_parser._COMMENT_RE.sub("", raw)
        if awl_parser.classify_awl_access(code) != "call":  # a CALL target is a block
            for name in awl_parser._SYMBOL_RE.findall(stripped):
                symbols.append(SymbolSite(name, block, idx))
    return S7Scan(tuple(out["addresses"]), tuple(symbols), tuple(out["indirect"]))


def _scl_access(code: str, start: int, end: int, in_var: bool) -> str:
    if in_var:
        return "declare"
    if code[end:].lstrip().startswith(":="):
        return "write"
    if code[:start].rstrip().endswith("=>"):
        return "write"  # an output parameter is written by the call
    return "read"


def scan_scl(text: str) -> S7Scan:
    """``%`` absolute operands and quoted global symbols in Siemens SCL text."""
    raw_lines = text.splitlines()
    code_lines = blank(text, _SCL_NOISE).splitlines()
    symbol_lines = blank(text, _SCL_COMMENT_OR_STRING).splitlines()
    addresses: list[AddressSite] = []
    symbols: list[SymbolSite] = []
    indirect: list[tuple[str, int, str]] = []
    block, decl = "", _Declarations()
    for idx, code in enumerate(code_lines, start=1):
        raw = raw_lines[idx - 1] if idx - 1 < len(raw_lines) else code
        named = symbol_lines[idx - 1] if idx - 1 < len(symbol_lines) else code
        header = _BLOCK_RE.match(named)  # quotes kept: `FUNCTION_BLOCK "FB_Motor"`
        if header and not _DECL_OPEN.match(code):
            block, decl = header.group(2).strip().strip('"'), _Declarations()
            continue
        was_var = decl.var
        if decl.skip(code) and not (decl.var and was_var):
            continue  # TYPE / DATA_BLOCK / STRUCT bodies; VAR lines are kept as declarations
        in_var = decl.var
        if _SCL_PEEK.search(code):
            indirect.append((block, idx, _quote(raw)))
        for m in _SCL_ADDR.finditer(code):
            # `%IW256:P` reads the peripheral, not the process image.
            token = ("P" + m.group(1)) if m.group(2) else m.group(1)
            address = parse_s7_program_address(token)
            if address is not None:
                access = _scl_access(code, m.start(), m.end(), in_var)
                addresses.append(AddressSite(address, access, block, idx, _quote(raw)))
        if idx - 1 < len(symbol_lines):
            for m in _SCL_QUOTED.finditer(symbol_lines[idx - 1]):
                symbols.append(SymbolSite(m.group(1), block, idx))
    return S7Scan(tuple(addresses), tuple(symbols), tuple(indirect))


__all__ = ["AddressSite", "S7Scan", "SymbolSite", "blank", "scan_awl", "scan_scl"]
