"""PLC program explainer + change-baseline MCP tools (READ-ONLY, exported files only).

A8 / market-research R3 #1 ask: "explain the legacy logic somebody else left
behind". These tools do the **structural extraction** — the agent does the
explaining. They only ever read one user-named EXPORTED text file (SCL/ST,
AWL/STL, Rockwell L5X) — never a live PLC upload, never a directory walk —
and every element carries source_file + line (rung number for ladder) so the
explanation must cite real locations. Advisory + regex/line/xml based, not a
full grammar; parse_errors are reported instead of raised.

``plc_program_snapshot`` / ``plc_program_drift`` / ``plc_program_history`` add the
change-control half: record the structure of the version you consider approved,
then ask a later export whether anything moved. The local store holds block
names, hashes and counts — never a declaration, a source line or a comment.
Deleting that history is CLI-only on purpose — an agent should not be one call
away from removing change-control evidence.
"""

from typing import Optional

from iaiops.core.brain import plc_program as ops
from iaiops.core.brain.plc_visibility import plc_visibility
from iaiops.core.governance import governed_tool
from iaiops.core.runtime.envelope import envelope_fields
from mcp_server._shared import mcp, tool_errors

MAX_BLOCKS = 50
MAX_VARS_PER_BLOCK = 100
MAX_XREF_HITS = 200
MAX_SECTION_LINES = 200


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_outline(path: str) -> dict:
    """[READ][risk=low] Structural outline of an EXPORTED PLC program file.

    Parses one exported text file (Siemens SCL/ST .scl/.st, AWL/STL .awl,
    Rockwell Studio 5000 .L5X — .txt is content-sniffed) and returns blocks
    (FB/FC/OB/DB/routines/AOIs) with VAR sections, IF/CASE branch inventory,
    timers/counters, and the call graph. Never uploads from a live PLC; reads
    exactly the named file (≤5 MB). Every element cites source_file + line
    (rung number for L5X ladder) — quote those citations when explaining.
    Malformed sections degrade to entries in parse_errors, never a crash.

    Args:
        path: Exported program file (.st/.scl/.awl/.l5x/.txt; must exist, ≤5 MB).

    Returns dict: {source_file, format, stats:{blocks, variables, call_edges,
        branches, timers_counters, comments, lines, parse_errors},
        blocks:[{name, kind, language, line, end_line, variables (≤100,
        variables_truncated), calls, branches, timers_counters, networks,
        comment}] (≤50, blocks_truncated), call_graph:[{caller, callee,
        source_file, line}], parse_errors, citation_note}.

    Example: plc_program_outline(path="~/exports/Line3_Conveyor.scl").
    """
    outline = ops.outline_program(path)
    return ops.outline_to_bounded_dict(
        outline, max_blocks=MAX_BLOCKS, max_vars_per_block=MAX_VARS_PER_BLOCK
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_xref(path: str, symbol: str) -> dict:
    """[READ][risk=low] Cross-reference one symbol in an exported PLC program.

    Finds every read/write/call/declare site of a symbol or absolute address
    (e.g. Motor_Run, "FB_Conveyor", DB10.DBX0.1, M0.0, Tank[2].Level) in one
    exported file, quoting the surrounding source line verbatim so the agent
    cites real code. Access classification is heuristic (op/regex based, not
    data-flow analysis): SCL ':='→write, '('→call; AWL T/=/S/R→write,
    L/A/O…→read, CALL→call; L5X OTE/OTL/OTU/RES and MOV-dest→write. For L5X,
    line is the rung number.

    Args:
        path: Exported program file (.st/.scl/.awl/.l5x/.txt; must exist, ≤5 MB).
        symbol: Symbol / tag / absolute address to trace (word-bounded match).

    Returns dict: {source_file, format, symbol, hit_count,
        hits:[{symbol, access, block, source_file, line, source_line}] (≤200),
        hits_truncated, by_access:{read, write, call, declare, reference}}.

    Example: plc_program_xref(path="~/exports/OB1.awl", symbol="M10.0").
    """
    resolved, _text, fmt = ops.load_program(path)
    hits = ops.find_symbol(path, symbol)
    by_access: dict[str, int] = {}
    for hit in hits:
        by_access[hit.access] = by_access.get(hit.access, 0) + 1
    return {
        "source_file": str(resolved),
        "format": fmt,
        "symbol": symbol,
        "hit_count": len(hits),
        "hits": [
            {
                "symbol": h.symbol,
                "access": h.access,
                "block": h.block,
                "source_file": h.source_file,
                "line": h.line,
                "source_line": h.source_line,
            }
            for h in hits[:MAX_XREF_HITS]
        ],
        "hits_truncated": len(hits) > MAX_XREF_HITS,  # legacy bool — see `is_truncated`
        "by_access": by_access,
        **envelope_fields(returned=min(len(hits), MAX_XREF_HITS), total=len(hits)),
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_section(path: str, block: str) -> dict:
    """[READ][risk=low] Source text of ONE named block from an exported program.

    Returns the exact source of a single block (FB/FC/OB/DB name for SCL/AWL;
    Program.Routine or routine name for L5X — rungs are rendered as
    '[rung N] ...'), capped at 200 lines with an explicit truncated flag, so
    the agent reads exactly the section it is explaining instead of guessing.
    Unknown block names fail with the list of available blocks.

    Args:
        path: Exported program file (.st/.scl/.awl/.l5x/.txt; must exist, ≤5 MB).
        block: Block/routine name (case-insensitive; quotes optional).

    Returns dict: {source_file, format, block, kind, start_line, end_line,
        lines_returned, truncated, source, parse_errors}.

    Example: plc_program_section(path="~/exports/Line3.scl", block="FB_Conveyor").
    """
    return ops.block_section(path, block, max_lines=MAX_SECTION_LINES)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_visibility(path: str) -> dict:
    """[READ][risk=low] Maintainability / operational-risk profile of a legacy PLC program.

    The "what am I inheriting?" view over one EXPORTED program (SCL/ST, AWL/STL,
    Rockwell L5X): folds the structural outline into documentation coverage, the
    least-commented blocks, blocks nothing references (possible dead code), the
    complexity hotspots, risky constructs (unconditional JMPs, retentive RTO
    timers, loops), and a TRANSPARENT additive risk score whose every point cites
    its reason. Structural only — it anchors an engineer's review of a line
    somebody else left behind, not a semantic understanding. Reads exactly the
    named file (≤5 MB); never a live PLC upload. Every finding cites source_file +
    line (rung number for L5X ladder).

    Args:
        path: Exported program file (.st/.scl/.awl/.l5x/.txt; must exist, ≤5 MB).

    Returns dict: {source_file, fmt, stats:{blocks, call_edges, line_count,
        comment_count, comment_ratio, variables, branches, timers_counters},
        documentation:{comment_ratio, band ('well_commented'|'sparse'|
        'undocumented'), uncommented_block_count, uncommented_blocks},
        entry_points:[{name, kind}], unreferenced_blocks:[{name, kind,
        source_file, line}], complexity_hotspots:[{block, kind, score, branches,
        calls, timers_counters, source_file, line}], risky_constructs:{
        unconditional_jumps, unconditional_jump_count, loops, loop_count,
        retentive_timers, retentive_timer_count}, risk:{score (0..100), band
        ('low'|'medium'|'high'), reasons[]}, parse_errors, note}.

    Example: plc_program_visibility(path="~/exports/Line3_Conveyor.scl").
    """
    return plc_visibility(ops.outline_program(path))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_snapshot(
    path: str,
    name: Optional[str] = None,
    label: str = "",
    note: str = "",
) -> dict:
    """[READ][risk=low] Record an exported program's structure as a change baseline.

    A control program is a controlled document, and the usual way an undocumented
    change to one gets noticed is that somebody remembers. This gives the
    comparison a number: the file's SHA-256, plus a per-block structural
    fingerprint (name/kind/language, declared variables, calls, branch conditions,
    timers) that deliberately excludes line numbers, comments and block order — so
    adding a comment at the top of a file does not report the whole program as
    changed. Stored locally under the iaiops home as block names, hashes and
    counts — never a declaration, a source line or a comment — so the store is not
    a second copy of the program. Reads the named EXPORTED file only; never a live
    PLC upload.

    Re-snapshotting a byte-identical file records nothing and says so — a history
    padded with identical rows hides the rows that are not.

    Args:
        path: Exported program file (.st/.scl/.awl/.l5x/.txt; must exist, ≤5 MB).
        name: Program identity across exports. Defaults to the file's stem, and
            the result says which was used — the export path changes every time
            somebody opens the engineering station, the program does not.
        label: Short label, e.g. "approved v3.2 / MOC-118".
        note: Free note recorded with the snapshot.

    Returns dict: {status ('recorded'|'unchanged'), program, name_source,
        snapshot:{snapshot_id, taken_at, source_file, content_sha256, label, note},
        block_count, snapshot_count, previous_snapshot}.

    Example: plc_program_snapshot(path="~/exports/Line3.scl", label="approved v3.2").
    """
    from iaiops.core.brain import program_baseline as pb

    return pb.take_snapshot(path, name=name, label=label, note=note)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_drift(
    path: str,
    name: Optional[str] = None,
    against: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Has this program changed since its approved snapshot, and what moved?

    Three verdicts, and the wording of each is load-bearing. **identical** means
    the same SHA-256 and nothing else earns the word. **logic_changed** means the
    extracted structure differs — reported per block, naming which categories
    (variables / calls / branches / timers_counters) moved. **changed_outside_
    extracted_structure** means the bytes differ while every block fingerprint
    matched: usually comments or formatting, but these parsers extract structure
    rather than parse a grammar, so a real change inside a construct they do not
    model looks identical from here. Calling that "documentation only" would be
    the comfortable reading of evidence that does not support it, so it is not
    called that, and it is not a clearance — line and comment counts are reported
    beside it so a reviewer can see which way it leans.

    Nothing here decides whether a change was authorised; that is change control's
    job. No device is touched — this reads a file a person exported.

    Args:
        path: The current exported program file to check.
        name: Tracked program name (defaults to the file's stem).
        against: Snapshot id to compare with; default is the latest.

    Returns dict: {program, name_source, baseline:{snapshot_id, taken_at, label,
        source_file}, current:{source_file}, verdict, content_changed,
        structure_changed, content_sha256:{before, after}, blocks:{added[],
        removed[], changed:[{block, kind, line, previous_line, changed[]}],
        unchanged}, totals:{block_count, line_count, comment_count}, parse_errors,
        note, advisory}.

    Example: plc_program_drift(path="~/exports/Line3_today.scl", name="Line3").
    """
    from iaiops.core.brain import program_baseline as pb

    return pb.check_drift(path, name=name, against=against)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def plc_program_history(name: Optional[str] = None) -> dict:
    """[READ][risk=low] Tracked programs, or one program's snapshot history.

    Local read of the program-baseline store — no file is parsed and no device is
    touched. Nothing is ever pruned automatically: a change-control history that
    quietly drops last quarter's baseline is worse than one that grows, and a
    stored row is block names, hashes and counts rather than source. Removing history is a
    deliberate act and is CLI-only (`iaiops program forget`) — deleting
    change-control evidence should not be one tool call away.

    Args:
        name: Tracked program name. Omit for the list of every tracked program.

    Returns dict (listing): {store, program_count, programs:[{program,
        snapshot_count, latest, latest_taken_at}]}; (one program): {store,
        program, snapshot_count, snapshots:[{snapshot_id, taken_at, source_file,
        content_sha256, label, note}]}.

    Example: plc_program_history(name="Line3").
    """
    from iaiops.core.brain import program_baseline as pb

    return pb.history(name)
