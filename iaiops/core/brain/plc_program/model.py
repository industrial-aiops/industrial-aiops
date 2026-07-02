"""Data model for the legacy PLC program explainer (A8) — frozen, cite-first.

Every element carries ``source_file`` + ``line`` so the consuming agent can
quote exact source locations and never has to invent them. For Rockwell L5X
RLL routines ``line`` is the **rung number** (the natural citation unit of a
ladder export); for text formats (SCL/ST/AWL) it is the 1-based file line.

These are structural extraction results, NOT a semantic understanding of the
program — the LLM agent does the explaining, these dataclasses only anchor it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Variable:
    """A declared variable / tag / parameter with its declaration site."""

    name: str
    var_type: str  # declared data type as written (e.g. BOOL, TON, "UDT_Motor")
    section: str  # VAR_INPUT / VAR_OUTPUT / VAR_IN_OUT / VAR_STAT / VAR_TEMP /
    # VAR / CONSTANT / TAG / PARAMETER / LOCAL_TAG
    comment: str  # trailing or preceding comment text ('' if none)
    source_file: str
    line: int


@dataclass(frozen=True)
class Branch:
    """A control-flow branch point (IF/ELSIF/CASE/FOR/WHILE/REPEAT...)."""

    kind: str  # IF / ELSIF / CASE / FOR / WHILE / REPEAT / JMP
    condition: str  # the condition text as written (bounded), '' if not captured
    source_file: str
    line: int


@dataclass(frozen=True)
class TimerCounter:
    """A timer/counter usage (TON/TOF/TP/CTU/CTD/CTUD/RTO...)."""

    name: str  # instance / tag name ('' if only the instruction was seen)
    kind: str  # TON / TOF / TP / CTU / CTD / CTUD / RTO / S5-timer T<n> ...
    source_file: str
    line: int


@dataclass(frozen=True)
class CallEdge:
    """caller → callee edge in the program call graph, with the call site."""

    caller: str  # calling block name ('' if outside any recognized block)
    callee: str  # called FB/FC/routine/AOI name (FB instances resolved to type
    # when the declaration was seen)
    source_file: str
    line: int


@dataclass(frozen=True)
class Block:
    """One program unit: FB/FC/OB/DB (SCL/AWL), routine/AOI/program (L5X).

    For AWL, NETWORK boundaries are recorded as sub-entries in ``networks``
    (line-number pairs), not as separate blocks.
    """

    name: str
    kind: str  # FUNCTION_BLOCK / FUNCTION / ORGANIZATION_BLOCK / DATA_BLOCK /
    # TYPE / PROGRAM / ROUTINE / AOI
    language: str  # scl / awl / rll / st
    source_file: str
    line: int  # header line (or first rung number for an L5X RLL routine)
    end_line: int  # END_* line / last rung number (== line if unterminated)
    variables: tuple[Variable, ...] = ()
    calls: tuple[CallEdge, ...] = ()
    branches: tuple[Branch, ...] = ()
    timers_counters: tuple[TimerCounter, ...] = ()
    networks: tuple[tuple[int, str], ...] = ()  # (line, title) — AWL only
    comment: str = ""  # block TITLE / Description ('' if none)


@dataclass(frozen=True)
class ProgramOutline:
    """Unified structural outline of one exported program file."""

    source_file: str
    fmt: str  # scl | awl | l5x
    blocks: tuple[Block, ...] = ()
    call_edges: tuple[CallEdge, ...] = ()  # flattened union of block calls
    comment_count: int = 0
    line_count: int = 0
    parse_errors: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        """Plain-dict form (JSON-safe) for MCP/CLI emission."""
        return asdict(self)


@dataclass(frozen=True)
class XrefHit:
    """One read/write/call/declare site of a symbol, with the line quoted."""

    symbol: str
    access: str  # read / write / call / declare / reference
    block: str  # containing block/routine name ('' if unknown)
    source_file: str
    line: int  # file line, or rung number for L5X RLL content
    source_line: str  # the surrounding source line, verbatim (bounded)
