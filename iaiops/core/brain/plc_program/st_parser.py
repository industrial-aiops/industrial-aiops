"""Siemens SCL / IEC 61131-3 Structured Text structural extractor (READ-ONLY).

Line/regex based — this is **structural extraction, not a full ST grammar**.
Extracted: block headers (FUNCTION / FUNCTION_BLOCK / ORGANIZATION_BLOCK /
DATA_BLOCK / TYPE / PROGRAM) with end lines, VAR sections
(VAR_INPUT/OUTPUT/IN_OUT/STAT/TEMP/CONSTANT) with name/type/comment, call sites
(identifier followed by ``(`` that is not a keyword/operator — FB instance
calls are resolved to the instance's declared FB type when the declaration was
seen), IF/ELSIF/CASE/FOR/WHILE/REPEAT branch points, and TON/TOF/TP/CTU/CTD/
CTUD timer/counter declarations and calls.

Skipped (deliberately): expressions, assignments semantics, pragmas/attributes,
REGION markers, nested struct member types, multi-line declarations spanning
``;`` across lines, and any semantic typing. Malformed input never raises —
problems are appended to the returned ``parse_errors`` list.
"""

from __future__ import annotations

import re

from iaiops.core.brain.plc_program.model import (
    Block,
    Branch,
    CallEdge,
    ProgramOutline,
    TimerCounter,
    Variable,
)

_BLOCK_RE = re.compile(
    r"^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|PROGRAM|TYPE)\s+"
    r'("?[\w. ]+"?)',
    re.IGNORECASE,
)
_END_BLOCK_RE = re.compile(
    r"^\s*END_(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|PROGRAM|TYPE)\b",
    re.IGNORECASE,
)
_VAR_SECTION_RE = re.compile(
    r"^\s*(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_STAT|VAR_TEMP|VAR_GLOBAL|VAR CONSTANT"
    r"|VAR)\b",
    re.IGNORECASE,
)
_END_VAR_RE = re.compile(r"^\s*END_VAR\b", re.IGNORECASE)
_DECL_RE = re.compile(
    r'^\s*("?[\w.]+"?)\s*(?:\{[^}]*\})?\s*:\s*([^:;=]+?)\s*(?::=[^;]*)?;'
)
_CALL_RE = re.compile(r'\b("?[A-Za-z_][\w.]*"?)\s*\(')
_BRANCH_RE = re.compile(
    r"^\s*(?:\w+\s*:\s*)?(IF|ELSIF|CASE|FOR|WHILE|REPEAT)\b(.*)", re.IGNORECASE
)
_TIMER_TYPES = frozenset({"TON", "TOF", "TP", "CTU", "CTD", "CTUD", "TONR"})
# Not calls: ST keywords/operators/builtins commonly followed by '('.
_NOT_CALLS = frozenset(
    {
        "IF", "ELSIF", "WHILE", "UNTIL", "CASE", "FOR", "TO", "BY", "RETURN", "NOT",
        "AND", "OR", "XOR", "MOD", "THEN", "DO", "OF", "ELSE", "EXIT", "ARRAY",
        "ABS", "SQRT", "MIN", "MAX", "LIMIT", "SEL", "MUX", "CONCAT", "LEN",
        "INT_TO_REAL", "REAL_TO_INT", "DINT_TO_REAL", "TIME_TO_DINT", "WORD_TO_INT",
    }
)


def _strip_comments(text: str) -> tuple[list[str], list[str], int]:
    """Return (code_lines, comment_lines, comment_count), preserving line count.

    ``//`` and ``(* ... *)`` (possibly multi-line) comments are blanked out of
    ``code_lines`` and collected (per line) in ``comment_lines``.
    """
    lines = text.splitlines()
    code: list[str] = []
    comments: list[str] = []
    count = 0
    in_block = False
    for raw in lines:
        code_part: list[str] = []
        comment_part: list[str] = []
        i = 0
        while i < len(raw):
            if in_block:
                end = raw.find("*)", i)
                if end < 0:
                    comment_part.append(raw[i:])
                    i = len(raw)
                else:
                    comment_part.append(raw[i:end])
                    in_block = False
                    i = end + 2
            elif raw.startswith("//", i):
                comment_part.append(raw[i + 2 :].strip())
                count += 1
                i = len(raw)
            elif raw.startswith("(*", i):
                in_block = True
                count += 1
                i += 2
            else:
                code_part.append(raw[i])
                i += 1
        code.append("".join(code_part))
        comments.append(" ".join(p.strip() for p in comment_part if p.strip()))
    return code, comments, count


def _norm_name(token: str) -> str:
    return token.strip().strip('"').strip()


def parse_st(text: str, source_file: str) -> ProgramOutline:
    """Extract a structural outline from SCL/ST source. Never raises."""
    parse_errors: list[str] = []
    try:
        code, comments, comment_count = _strip_comments(text)
    except Exception as exc:  # pragma: no cover - defensive
        return ProgramOutline(
            source_file=source_file, fmt="scl",
            parse_errors=(f"comment stripping failed: {exc}",),
        )

    blocks: list[Block] = []
    cur: dict | None = None  # mutable scratch for the block being read
    var_section: str | None = None
    instance_types: dict[str, str] = {}

    def close_block(end_line: int) -> None:
        nonlocal cur
        if cur is None:
            return
        blocks.append(
            Block(
                name=cur["name"], kind=cur["kind"], language="scl",
                source_file=source_file, line=cur["line"], end_line=end_line,
                variables=tuple(cur["vars"]), calls=tuple(cur["calls"]),
                branches=tuple(cur["branches"]),
                timers_counters=tuple(cur["timers"]), comment=cur["comment"],
            )
        )
        cur = None

    for idx, line in enumerate(code, start=1):
        try:
            m = _BLOCK_RE.match(line)
            if m:
                if cur is not None:
                    parse_errors.append(
                        f"line {idx}: new block '{m.group(2)}' before "
                        f"END_{cur['kind']} of '{cur['name']}' — closing implicitly"
                    )
                    close_block(idx - 1)
                cur = {
                    "name": _norm_name(m.group(2)), "kind": m.group(1).upper(),
                    "line": idx, "vars": [], "calls": [], "branches": [],
                    "timers": [], "comment": comments[idx - 1],
                }
                var_section = None
                continue
            if _END_BLOCK_RE.match(line):
                close_block(idx)
                var_section = None
                continue
            m = _VAR_SECTION_RE.match(line)
            if m and cur is not None:
                var_section = m.group(1).upper().replace(" ", "_")
                continue
            if _END_VAR_RE.match(line):
                var_section = None
                continue
            if var_section and cur is not None:
                m = _DECL_RE.match(line)
                if m:
                    name = _norm_name(m.group(1))
                    var_type = m.group(2).strip()
                    cur["vars"].append(
                        Variable(
                            name=name, var_type=var_type, section=var_section,
                            comment=comments[idx - 1], source_file=source_file,
                            line=idx,
                        )
                    )
                    base_type = _norm_name(var_type).upper()
                    if base_type in _TIMER_TYPES:
                        cur["timers"].append(
                            TimerCounter(name=name, kind=base_type,
                                         source_file=source_file, line=idx)
                        )
                    instance_types[name.upper()] = _norm_name(var_type)
                continue
            if cur is None:
                continue
            m = _BRANCH_RE.match(line)
            if m:
                cur["branches"].append(
                    Branch(kind=m.group(1).upper(),
                           condition=m.group(2).strip()[:120],
                           source_file=source_file, line=idx)
                )
            for cm in _CALL_RE.finditer(line):
                raw_name = _norm_name(cm.group(1))
                upper = raw_name.upper()
                if upper in _NOT_CALLS or "." in raw_name:
                    continue
                callee = instance_types.get(upper, raw_name)
                if callee.upper() in _TIMER_TYPES or upper in _TIMER_TYPES:
                    cur["timers"].append(
                        TimerCounter(name=raw_name, kind=callee.upper(),
                                     source_file=source_file, line=idx)
                    )
                cur["calls"].append(
                    CallEdge(caller=cur["name"], callee=callee,
                             source_file=source_file, line=idx)
                )
        except Exception as exc:
            parse_errors.append(f"line {idx}: skipped ({exc})")

    if cur is not None:
        parse_errors.append(
            f"block '{cur['name']}' has no END_{cur['kind']} (truncated file?)"
        )
        close_block(len(code))

    call_edges = tuple(edge for blk in blocks for edge in blk.calls)
    return ProgramOutline(
        source_file=source_file, fmt="scl", blocks=tuple(blocks),
        call_edges=call_edges, comment_count=comment_count,
        line_count=len(code), parse_errors=tuple(parse_errors),
    )
