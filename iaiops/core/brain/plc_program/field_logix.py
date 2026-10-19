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
_WRITE_OPS = re.compile(r"\b(OTE|OTL|OTU|RES|ONS)\(\s*([^,)]+?)\s*\)", re.I)
_DEST_OPS = re.compile(r"\b(MOV|COP|CPS|CPT)\(\s*[^)]*?,\s*([^,)]+?)\s*\)", re.I)
_ST_ASSIGN = re.compile(r"^\s*([A-Za-z_][\w.\[\]]*)\s*:=")


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


def _writes(text: str) -> set[str]:
    found = {base_of(m.group(2)) for m in _WRITE_OPS.finditer(text)}
    found |= {base_of(m.group(2)) for m in _DEST_OPS.finditer(text)}
    if m := _ST_ASSIGN.match(text):
        found.add(base_of(m.group(1)))
    return found


def site_index(text: str, source_file: str) -> dict[str, list[dict]]:
    """``{base tag (casefolded): [site, ...]}`` over every rung and ST line."""
    index: dict[str, list[dict]] = {}
    for block, number, rtext, _comment in rung_texts(text, source_file):
        writes = _writes(rtext)
        for base in dict.fromkeys(m.group(1).casefold() for m in _IDENT.finditer(rtext)):
            index.setdefault(base, []).append(
                {
                    "access": "write" if base in writes else "read",
                    "block": block,
                    "line": number,
                    "source_line": rtext.strip()[:_MAX_QUOTE],
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
