"""Siemens AWL/STL (statement list) structural extractor (READ-ONLY).

Line/regex based — **structural extraction, not an STL interpreter**.
Extracted: block headers (FUNCTION_BLOCK/FUNCTION/ORGANIZATION_BLOCK/DATA_BLOCK
+ END_*), NETWORK boundaries with TITLE, per-line ops (L/T load-transfer,
A/AN/O/ON/X/XN bit logic, =/S/R bit writes, CALL/UC/CC block calls), absolute
address references (DBn.DBX/DBB/DBW/DBD, I/Q/M with B/W/D widths, T/C timers
and counters, PIW/PQW), and quoted symbolic names.

Skipped (deliberately): accumulator semantics, jump-label flow (only JMP-family
mnemonics are noted as branches), pointer/AR arithmetic, and data-block initial
values. Malformed input never raises — problems land in ``parse_errors``.
"""

from __future__ import annotations

import re

from iaiops.core.brain.plc_program.model import (
    Block,
    Branch,
    CallEdge,
    ProgramOutline,
    TimerCounter,
)

_BLOCK_RE = re.compile(
    r'^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK)\s+("?[\w. ]+"?)',
    re.IGNORECASE,
)
_END_BLOCK_RE = re.compile(
    r"^\s*END_(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK)\b",
    re.IGNORECASE,
)
_NETWORK_RE = re.compile(r"^\s*NETWORK\b", re.IGNORECASE)
_TITLE_RE = re.compile(r"^\s*TITLE\s*=\s*(.*)", re.IGNORECASE)
_COMMENT_RE = re.compile(r"//(.*)")
_CALL_RE = re.compile(r'^\s*(?:CALL|UC|CC)\s+("?[\w. ]+"?)\s*(?:,\s*("?[\w. ]+"?))?', re.IGNORECASE)
_OP_RE = re.compile(r"^\s*(L|T|A|AN|O|ON|X|XN|=|S|R|FP|FN|SET|CLR)\s+(.+?)\s*;?\s*$")
_JMP_RE = re.compile(r"^\s*(JU|JC|JCN|JL|SPA|SPB|SPBN)\s+(\w+)", re.IGNORECASE)
ADDRESS_RE = re.compile(
    r"\b(DB\d+\.DB[XBWD]\s*\d+(?:\.\d+)?|DB\d+|[IQMEA][BWD]?\s*\d+(?:\.\d+)?"
    r"|P[IQ][WBD]\s*\d+|T\s*\d+|C\s*\d+)\b"
)
_SYMBOL_RE = re.compile(r'"([^"]+)"')
_TIMER_OP_RE = re.compile(r"^\s*(SP|SE|SD|SS|SF|CU|CD)\s+([TC]\s*\d+)", re.IGNORECASE)
_WRITE_OPS = frozenset({"T", "=", "S", "R"})


def parse_awl(text: str, source_file: str) -> ProgramOutline:
    """Extract a structural outline from AWL/STL source. Never raises."""
    parse_errors: list[str] = []
    lines = text.splitlines()
    blocks: list[Block] = []
    comment_count = 0
    cur: dict | None = None
    pending_network: int | None = None  # NETWORK line awaiting its TITLE

    def close_block(end_line: int) -> None:
        nonlocal cur
        if cur is None:
            return
        blocks.append(
            Block(
                name=cur["name"],
                kind=cur["kind"],
                language="awl",
                source_file=source_file,
                line=cur["line"],
                end_line=end_line,
                calls=tuple(cur["calls"]),
                branches=tuple(cur["branches"]),
                timers_counters=tuple(cur["timers"]),
                networks=tuple(cur["networks"]),
                comment=cur["comment"],
            )
        )
        cur = None

    for idx, raw in enumerate(lines, start=1):
        try:
            if _COMMENT_RE.search(raw):
                comment_count += 1
            line = _COMMENT_RE.sub("", raw)
            m = _BLOCK_RE.match(line)
            if m:
                if cur is not None:
                    parse_errors.append(
                        f"line {idx}: new block before END_{cur['kind']} of "
                        f"'{cur['name']}' — closing implicitly"
                    )
                    close_block(idx - 1)
                cur = {
                    "name": m.group(2).strip().strip('"'),
                    "kind": m.group(1).upper(),
                    "line": idx,
                    "calls": [],
                    "branches": [],
                    "timers": [],
                    "networks": [],
                    "comment": "",
                }
                continue
            if _END_BLOCK_RE.match(line):
                close_block(idx)
                continue
            if _NETWORK_RE.match(line):
                if cur is None:
                    parse_errors.append(f"line {idx}: NETWORK outside any block")
                    continue
                pending_network = idx
                cur["networks"].append((idx, ""))
                continue
            tm = _TITLE_RE.match(line)
            if tm and cur is not None and pending_network is not None:
                title = tm.group(1).strip()[:120]
                cur["networks"][-1] = (pending_network, title)
                if cur["networks"][0][0] == pending_network and not cur["comment"]:
                    cur["comment"] = title
                pending_network = None
                continue
            if cur is None:
                continue
            cm = _CALL_RE.match(line)
            if cm:
                cur["calls"].append(
                    CallEdge(
                        caller=cur["name"],
                        callee=cm.group(1).strip().strip('"'),
                        source_file=source_file,
                        line=idx,
                    )
                )
                continue
            jm = _JMP_RE.match(line)
            if jm:
                cur["branches"].append(
                    Branch(
                        kind="JMP",
                        condition=f"{jm.group(1)} {jm.group(2)}",
                        source_file=source_file,
                        line=idx,
                    )
                )
                continue
            tim = _TIMER_OP_RE.match(line)
            if tim:
                addr = tim.group(2).replace(" ", "")
                cur["timers"].append(
                    TimerCounter(
                        name=addr, kind=tim.group(1).upper(), source_file=source_file, line=idx
                    )
                )
        except Exception as exc:
            parse_errors.append(f"line {idx}: skipped ({exc})")

    if cur is not None:
        parse_errors.append(f"block '{cur['name']}' has no END_{cur['kind']} (truncated file?)")
        close_block(len(lines))

    call_edges = tuple(edge for blk in blocks for edge in blk.calls)
    return ProgramOutline(
        source_file=source_file,
        fmt="awl",
        blocks=tuple(blocks),
        call_edges=call_edges,
        comment_count=comment_count,
        line_count=len(lines),
        parse_errors=tuple(parse_errors),
    )


def classify_awl_access(line: str) -> str:
    """Classify one AWL statement line as read/write/call/reference.

    T/=/S/R write their operand; L/A/O/... read it; CALL/UC/CC call it.
    Unrecognized lines that still mention the operand are 'reference'.
    """
    stripped = _COMMENT_RE.sub("", line)
    if _CALL_RE.match(stripped):
        return "call"
    om = _OP_RE.match(stripped)
    if om:
        return "write" if om.group(1) in _WRITE_OPS else "read"
    if _TIMER_OP_RE.match(stripped):
        return "write"
    return "reference"


def awl_operand_tokens(line: str) -> list[str]:
    """All address + quoted-symbol tokens on one line (normalized, no spaces)."""
    stripped = _COMMENT_RE.sub("", line)
    tokens = [a.replace(" ", "") for a in ADDRESS_RE.findall(stripped)]
    tokens.extend(_SYMBOL_RE.findall(stripped))
    return tokens
