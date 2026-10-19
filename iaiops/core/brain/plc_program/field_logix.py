"""Rockwell L5X tags and where the logic touches them — parsed once, indexed.

For a Logix controller the tag path IS the address the CIP connector reads by,
so a declared tag (controller scope, or ``Program:<name>.<tag>``) is the unit of
comparison. Sites are found by indexing every rung / ST line ONCE by the base
tag each operand belongs to (``Tank[2].Level`` → ``Tank``), so a 5 MB export
with a thousand tags is one pass, not a thousand re-parses.

A site belongs to the WHOLE tag. For a configured element or member
(``Tank[2]``, ``RunTmr.ACC``) the sites listed are the tag's, and the result
says so (``sites_scope: whole_tag``) rather than implying that rung touches
that element.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 — parsing goes through reject_unsafe_xml first
from dataclasses import dataclass

from iaiops.core.brain.plc_program.l5x_parser import reject_unsafe_xml, rung_texts
from iaiops.core.brain.plc_program.model import ProgramOutline

_MAX_QUOTE = 160
_SPLIT = re.compile(r"[.\[{]")
_IDENT = re.compile(r"(?<![\w.:\]#])([A-Za-z_]\w*)(?!\w)(?!\s*\()")
#: Destination operand (0-based) per instruction. Anything not listed is read-only
#: here — "who writes this?" must not be answered from a guess at an operand order.
_DEST_SLOT = {
    **dict.fromkeys(("OTE", "OTL", "OTU", "RES", "ONS", "CLR"), 0),
    **dict.fromkeys(("TON", "TOF", "RTO", "CTU", "CTD", "CPT"), 0),
    **dict.fromkeys(("MOV", "COP", "CPS", "FLL", "NOT", "NEG", "ABS", "SQR", "TOD", "FRD"), 1),
    **dict.fromkeys(("OSR", "OSF"), 1),
    **dict.fromkeys(("ADD", "SUB", "MUL", "DIV", "MOD", "AND", "OR", "XOR", "BAND", "BOR"), 2),
    "MVM": 3,
}
_CALL = re.compile(r"\b([A-Za-z_]\w*)\(")
_ST_ASSIGN = re.compile(r"(?<![\w.:\]])([A-Za-z_][\w.\[\]]*)\s*:=")
_ST_NOISE = re.compile(r"//[^\n]*|/\*.*?\*/|\(\*.*?\*\)|'(?:\$.|[^'\n])*'", re.S)


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


def base_of(operand: str) -> str:
    """``Tank[2].Level`` → ``tank`` (casefolded base tag name)."""
    return _SPLIT.split(operand.strip(), maxsplit=1)[0].casefold()


def logix_ref_key(ref: str) -> tuple[str, bool]:
    """A configured Logix ref → (key of the tag it lives in, is it the whole tag).

    ``Program:Main.RunTmr.ACC`` lives in ``Program:Main.RunTmr``; ``Tank[2]`` and
    ``Tank{3}`` live in ``Tank``. The member/element is part of that one tag —
    the same memory — so it joins as ``member_of_tag``, never as a near name.
    """
    text = str(ref or "").strip()
    prefix, rest = "", text
    if text.casefold().startswith("program:"):
        head, _, rest = text[len("program:") :].partition(".")
        prefix = f"Program:{head}."
    whole = prefix + _SPLIT.split(rest, maxsplit=1)[0]
    return whole.casefold(), whole.casefold() == text.casefold()


def controller_identity(text: str) -> dict[str, str]:
    """``{name, processor_type}`` of the exporting controller ('' when absent)."""
    try:
        reject_unsafe_xml(text)
        root = ET.fromstring(text)  # noqa: S314 # nosec B314 — DTD/entities rejected above
    except (ValueError, ET.ParseError):
        return {"name": "", "processor_type": ""}
    ctrl = root.find(".//Controller")
    if ctrl is None:
        return {"name": "", "processor_type": ""}
    return {"name": ctrl.get("Name", ""), "processor_type": ctrl.get("ProcessorType", "")}


def _operands(text: str, open_at: int) -> list[str]:
    """Top-level comma-separated operands of the call whose ``(`` is at ``open_at``."""
    depth, start, parts = 0, open_at + 1, []
    for i in range(open_at, len(text)):
        ch = text[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth == 0:
                parts.append(text[start:i])
                return [p.strip() for p in parts]
        elif ch == "," and depth == 1:
            parts.append(text[start:i])
            start = i + 1
    return [p.strip() for p in parts]


def _writes(text: str) -> set[str]:
    """Base tags this rung / ST line writes (destination operands, ST assignments)."""
    found: set[str] = set()
    for m in _CALL.finditer(text):
        slot = _DEST_SLOT.get(m.group(1).upper())
        if slot is None:
            continue
        operands = _operands(text, m.end() - 1)
        if slot < len(operands) and operands[slot] and operands[slot] != "?":
            found.add(base_of(operands[slot]))
    found |= {base_of(m.group(1)) for m in _ST_ASSIGN.finditer(text)}
    return found


def _uncommented(entries: list[tuple[str, int, str, str]]) -> list[tuple[str, int, str]]:
    """Blank ST comments and strings per routine — a block comment spans <Line>s."""
    out: list[tuple[str, int, str]] = []
    by_block: dict[str, list[tuple[int, str]]] = {}
    for block, number, rtext, _comment in entries:
        by_block.setdefault(block, []).append((number, rtext.replace("\n", " ")))
    for block, rows in by_block.items():
        joined = "\n".join(r for _n, r in rows)
        blanked = _ST_NOISE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), joined)
        for (number, _r), code in zip(rows, blanked.split("\n"), strict=False):
            out.append((block, number, code))
    return out


def site_index(text: str, source_file: str) -> dict[str, list[dict]]:
    """``{base tag (casefolded): [site, ...]}`` over every rung and ST line."""
    index: dict[str, list[dict]] = {}
    entries = rung_texts(text, source_file)
    quotes = {(b, n): t for b, n, t, _c in entries}
    for block, number, code in _uncommented(entries):
        writes = _writes(code)
        for base in dict.fromkeys(m.group(1).casefold() for m in _IDENT.finditer(code)):
            index.setdefault(base, []).append(
                {
                    "access": "write" if base in writes else "read",
                    "block": block,
                    "line": number,
                    "source_line": quotes.get((block, number), code).strip()[:_MAX_QUOTE],
                }
            )
    return index


def sites_for(tag: LogixTag, index: dict[str, list[dict]], shadowing: set[str]) -> list[dict]:
    """The sites of one declared tag, honouring program scope and shadowing."""
    rows = []
    for site in index.get(tag.name.casefold(), []):
        program = site["block"].split(".", 1)[0]
        if tag.program and program != tag.program:
            continue  # another program's rungs see their own tag of that name
        if not tag.program and program in shadowing:
            continue  # a program-scoped tag of the same name shadows this one there
        rows.append(site)
    return rows


__all__ = [
    "LogixTag",
    "base_of",
    "controller_identity",
    "logix_ref_key",
    "logix_tags",
    "site_index",
    "sites_for",
]
