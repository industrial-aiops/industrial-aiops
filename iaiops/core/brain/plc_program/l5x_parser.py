"""Rockwell L5X (Studio 5000 XML export) structural extractor (READ-ONLY).

Uses **stdlib xml.etree only**, with defusedxml-style hardening: the raw text
is scanned for ``<!DOCTYPE`` / ``<!ENTITY`` and rejected before parsing, so DTD
and entity tricks (XXE, billion-laughs) never reach the parser. Limitation:
because ``defusedxml`` is not a dependency, this is a pre-parse text check plus
modern CPython's default no-external-entity behavior — not a full hardened
parser; files that legitimately carry a DOCTYPE are rejected rather than risked.

Extracted: Controller + Program scoped Tags (name/type/description), Programs →
Routines (RLL rung Text with rung Number + Comment; ST content lines), AOI
definitions (name + parameters), JSR/SBR routine calls, AOI invocations in rung
text, TON/TOF/RTO/CTU/CTD instruction sites. ``line`` on RLL elements is the
**rung number**; on ST content it is the ``<Line Number=...>`` value.

Skipped (deliberately): FBD/SFC routine bodies (counted, not decoded), UDT
member structure, I/O module configuration, and rung-branch topology (only the
rung text is preserved). Malformed XML never raises — the error is reported in
``parse_errors`` and whatever was extracted before the failure is returned.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 — pre-parse entity/DTD rejection below

from iaiops.core.brain.plc_program.model import (
    Block,
    CallEdge,
    ProgramOutline,
    TimerCounter,
    Variable,
)

_FORBIDDEN_MARKUP = ("<!DOCTYPE", "<!ENTITY")
_JSR_RE = re.compile(r"\bJSR\(\s*([\w.]+)", re.IGNORECASE)
_TIMER_RE = re.compile(r"\b(TON|TOF|RTO|CTU|CTD)\(\s*([\w.\[\]]+)", re.IGNORECASE)
_INSTR_RE = re.compile(r"\b([A-Za-z_]\w*)\(")


def reject_unsafe_xml(text: str) -> None:
    """Raise ValueError if the document declares a DTD or entities (XXE guard)."""
    upper = text[:200_000].upper()  # declarations live in the prolog
    for marker in _FORBIDDEN_MARKUP:
        if marker in upper:
            raise ValueError(
                f"L5X rejected: document contains '{marker}' — DTD/entity "
                "declarations are not allowed (XXE hardening). Re-export the "
                "file without a DOCTYPE."
            )


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _description(elem: ET.Element) -> str:
    return _text(elem.find("Description"))


def _tags(parent: ET.Element, section: str, source_file: str) -> list[Variable]:
    out: list[Variable] = []
    for tag in parent.findall("./Tags/Tag"):
        out.append(
            Variable(
                name=tag.get("Name", ""), var_type=tag.get("DataType", ""),
                section=section, comment=_description(tag),
                source_file=source_file, line=0,
            )
        )
    return out


def _routine_block(
    routine: ET.Element, program: str, source_file: str, errors: list[str]
) -> Block:
    name = routine.get("Name", "")
    rtype = routine.get("Type", "RLL")
    calls: list[CallEdge] = []
    timers: list[TimerCounter] = []
    first, last = 0, 0
    full_name = f"{program}.{name}" if program else name

    def scan_text(text: str, line: int) -> None:
        for jm in _JSR_RE.finditer(text):
            calls.append(
                CallEdge(caller=full_name, callee=jm.group(1),
                         source_file=source_file, line=line)
            )
        for tm in _TIMER_RE.finditer(text):
            timers.append(
                TimerCounter(name=tm.group(2), kind=tm.group(1).upper(),
                             source_file=source_file, line=line)
            )

    if rtype == "RLL":
        rungs = routine.findall("./RLLContent/Rung")
        numbers: list[int] = []
        for rung in rungs:
            try:
                num = int(rung.get("Number", "0"))
            except ValueError:
                errors.append(f"routine {full_name}: non-numeric rung Number")
                num = 0
            numbers.append(num)
            scan_text(_text(rung.find("Text")), num)
        if numbers:
            first, last = min(numbers), max(numbers)
    elif rtype == "ST":
        for line_el in routine.findall("./STContent/Line"):
            try:
                num = int(line_el.get("Number", "0"))
            except ValueError:
                num = 0
            last = max(last, num)
            scan_text(_text(line_el), num)
    else:
        errors.append(f"routine {full_name}: type {rtype} body not decoded (FBD/SFC)")

    return Block(
        name=full_name, kind="ROUTINE", language="rll" if rtype == "RLL" else "st",
        source_file=source_file, line=first, end_line=last,
        calls=tuple(calls), timers_counters=tuple(timers),
        comment=_description(routine),
    )


def parse_l5x(text: str, source_file: str) -> ProgramOutline:
    """Extract a structural outline from an L5X export. Never raises."""
    errors: list[str] = []
    blocks: list[Block] = []
    try:
        reject_unsafe_xml(text)
        root = ET.fromstring(text)  # noqa: S314 # nosec B314 — DTD/entities rejected above
    except (ValueError, ET.ParseError) as exc:
        return ProgramOutline(
            source_file=source_file, fmt="l5x",
            line_count=text.count("\n") + 1,
            parse_errors=(f"L5X parse failed: {exc}",),
        )

    controller = root.find(".//Controller")
    scope = controller if controller is not None else root

    controller_tags = _tags(scope, "TAG", source_file)
    if controller_tags:
        blocks.append(
            Block(
                name=scope.get("Name", "Controller"), kind="DATA_BLOCK",
                language="rll", source_file=source_file, line=0, end_line=0,
                variables=tuple(controller_tags), comment="controller-scoped tags",
            )
        )

    for aoi in scope.findall(".//AddOnInstructionDefinitions/AddOnInstructionDefinition"):
        params = [
            Variable(
                name=p.get("Name", ""), var_type=p.get("DataType", ""),
                section="PARAMETER", comment=_description(p),
                source_file=source_file, line=0,
            )
            for p in aoi.findall("./Parameters/Parameter")
        ]
        blocks.append(
            Block(
                name=aoi.get("Name", ""), kind="AOI", language="rll",
                source_file=source_file, line=0, end_line=0,
                variables=tuple(params), comment=_description(aoi),
            )
        )
    aoi_names = {b.name for b in blocks if b.kind == "AOI"}

    for program in scope.findall(".//Programs/Program"):
        pname = program.get("Name", "")
        local = _tags(program, "LOCAL_TAG", source_file)
        blocks.append(
            Block(
                name=pname, kind="PROGRAM", language="rll",
                source_file=source_file, line=0, end_line=0,
                variables=tuple(local), comment=_description(program),
            )
        )
        for routine in program.findall("./Routines/Routine"):
            try:
                blk = _routine_block(routine, pname, source_file, errors)
            except Exception as exc:
                errors.append(
                    f"routine {pname}.{routine.get('Name', '?')}: skipped ({exc})"
                )
                continue
            # AOI invocations: instruction names matching an AOI definition.
            aoi_calls: list[CallEdge] = []
            if aoi_names:
                for rung in routine.findall("./RLLContent/Rung"):
                    rtext = _text(rung.find("Text"))
                    rnum = int(rung.get("Number", "0") or 0)
                    for im in _INSTR_RE.finditer(rtext):
                        if im.group(1) in aoi_names:
                            aoi_calls.append(
                                CallEdge(caller=blk.name, callee=im.group(1),
                                         source_file=source_file, line=rnum)
                            )
            if aoi_calls:
                blk = Block(
                    name=blk.name, kind=blk.kind, language=blk.language,
                    source_file=blk.source_file, line=blk.line,
                    end_line=blk.end_line, variables=blk.variables,
                    calls=blk.calls + tuple(aoi_calls),
                    timers_counters=blk.timers_counters, comment=blk.comment,
                )
            blocks.append(blk)

    call_edges = tuple(edge for blk in blocks for edge in blk.calls)
    return ProgramOutline(
        source_file=source_file, fmt="l5x", blocks=tuple(blocks),
        call_edges=call_edges, comment_count=len(root.findall(".//Comment"))
        + len(root.findall(".//Description")),
        line_count=text.count("\n") + 1, parse_errors=tuple(errors),
    )


def rung_texts(text: str, source_file: str) -> list[tuple[str, int, str, str]]:
    """(block_name, rung_number, rung_text, rung_comment) for all RLL rungs.

    Also yields ST content lines as (block, line_number, text, ''). Used by
    xref and section extraction. Raises ValueError on unsafe/unparseable XML.
    """
    reject_unsafe_xml(text)
    root = ET.fromstring(text)  # noqa: S314 # nosec B314 — DTD/entities rejected above
    out: list[tuple[str, int, str, str]] = []
    for program in root.findall(".//Programs/Program"):
        pname = program.get("Name", "")
        for routine in program.findall("./Routines/Routine"):
            full = f"{pname}.{routine.get('Name', '')}"
            for rung in routine.findall("./RLLContent/Rung"):
                out.append(
                    (full, int(rung.get("Number", "0") or 0),
                     _text(rung.find("Text")), _text(rung.find("Comment")))
                )
            for line_el in routine.findall("./STContent/Line"):
                out.append(
                    (full, int(line_el.get("Number", "0") or 0), _text(line_el), "")
                )
    return out
