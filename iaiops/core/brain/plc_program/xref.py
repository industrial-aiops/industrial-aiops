"""Symbol cross-reference over exported PLC program text (READ-ONLY, cite-first).

``find_symbol(path, symbol)`` returns every read/write/call/declare site of a
symbol (or absolute address like ``DB10.DBX0.1`` / ``M0.0`` / ``Motor.Run``)
with the surrounding source line quoted verbatim — the agent explains, the
xref anchors. Access classification is heuristic (regex/op based, not a data
flow analysis) and is documented per format:

* SCL/ST — ``sym := ...`` → write; ``sym(...)`` → call; inside a VAR section →
  declare; any other mention → read.
* AWL — op mnemonics: T/=/S/R write, L/A/AN/O/... read, CALL/UC/CC call.
* L5X — OTE/OTL/OTU/RES(sym) and the last operand of MOV/COP/CPT → write;
  rung-text mention otherwise → read; ``line`` is the rung number.
"""

from __future__ import annotations

import re

from iaiops.core.brain.plc_program import awl_parser
from iaiops.core.brain.plc_program.l5x_parser import rung_texts
from iaiops.core.brain.plc_program.model import XrefHit
from iaiops.core.brain.plc_program.outline import load_program
from iaiops.core.brain.plc_program.st_parser import _BLOCK_RE  # shared header regex

_MAX_QUOTE = 200
_ST_VAR_START = re.compile(r"^\s*VAR(_INPUT|_OUTPUT|_IN_OUT|_STAT|_TEMP|_GLOBAL)?\b", re.IGNORECASE)
_ST_VAR_END = re.compile(r"^\s*END_VAR\b", re.IGNORECASE)
_L5X_WRITE_RE = re.compile(r"\b(OTE|OTL|OTU|RES|ONS)\(\s*([\w.\[\]]+)\s*\)")
_L5X_DEST_RE = re.compile(r"\b(MOV|COP|CPS|CPT)\(\s*[^)]*?,\s*([\w.\[\]]+)\s*\)")


def _mention_re(symbol: str) -> re.Pattern[str]:
    """Word-bounded, case-insensitive match of the symbol (address-safe)."""
    return re.compile(
        r"(?<![\w.])" + re.escape(symbol.strip().strip('"')) + r"(?![\w])",
        re.IGNORECASE,
    )


def _quote(line: str) -> str:
    return line.strip()[:_MAX_QUOTE]


def _st_hits(lines: list[str], symbol: str, source_file: str) -> list[XrefHit]:
    pattern = _mention_re(symbol)
    hits: list[XrefHit] = []
    block, in_var = "", False
    for idx, raw in enumerate(lines, start=1):
        bm = _BLOCK_RE.match(raw)
        if bm:
            block, in_var = bm.group(2).strip().strip('"'), False
        elif _ST_VAR_START.match(raw):
            in_var = True
        elif _ST_VAR_END.match(raw):
            in_var = False
        m = pattern.search(raw)
        if not m:
            continue
        after = raw[m.end() :].lstrip()
        if in_var and re.match(r"[:{]", after or ":"):
            access = "declare"
        elif after.startswith(":="):
            access = "write"
        elif after.startswith("("):
            access = "call"
        else:
            access = "read"
        hits.append(
            XrefHit(
                symbol=symbol,
                access=access,
                block=block,
                source_file=source_file,
                line=idx,
                source_line=_quote(raw),
            )
        )
    return hits


def _awl_hits(lines: list[str], symbol: str, source_file: str) -> list[XrefHit]:
    pattern = _mention_re(symbol.replace(" ", ""))
    hits: list[XrefHit] = []
    block = ""
    for idx, raw in enumerate(lines, start=1):
        bm = _BLOCK_RE.match(raw)
        if bm:
            block = bm.group(2).strip().strip('"')
        tokens = awl_parser.awl_operand_tokens(raw)
        norm = raw.replace(" ", "")
        if not (any(pattern.fullmatch(t) for t in tokens) or pattern.search(norm)):
            continue
        hits.append(
            XrefHit(
                symbol=symbol,
                access=awl_parser.classify_awl_access(raw),
                block=block,
                source_file=source_file,
                line=idx,
                source_line=_quote(raw),
            )
        )
    return hits


def _l5x_hits(text: str, symbol: str, source_file: str) -> list[XrefHit]:
    pattern = _mention_re(symbol)
    hits: list[XrefHit] = []
    for block, num, rtext, _comment in rung_texts(text, source_file):
        if not pattern.search(rtext):
            continue
        wanted = symbol.strip().lower()
        writes = {m.group(2).lower() for m in _L5X_WRITE_RE.finditer(rtext)}
        writes |= {m.group(2).lower() for m in _L5X_DEST_RE.finditer(rtext)}
        access = "write" if wanted in writes else "read"
        hits.append(
            XrefHit(
                symbol=symbol,
                access=access,
                block=block,
                source_file=source_file,
                line=num,
                source_line=_quote(rtext),
            )
        )
    return hits


def find_symbol(path: str, symbol: str) -> tuple[XrefHit, ...]:
    """Every read/write/call/declare site of ``symbol`` in the exported file.

    Never raises on malformed program content (an unreadable L5X yields zero
    hits only via its documented ValueError from the XXE guard, which callers
    surface); path problems raise ValueError from validation.
    """
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    resolved, text, fmt = load_program(path)
    source_file = str(resolved)
    if fmt == "l5x":
        return tuple(_l5x_hits(text, symbol, source_file))
    lines = text.splitlines()
    if fmt == "awl":
        return tuple(_awl_hits(lines, symbol, source_file))
    return tuple(_st_hits(lines, symbol, source_file))
