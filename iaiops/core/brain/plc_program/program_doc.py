"""`iaiops program doc` — one exported program as a self-contained HTML document.

Documentation is the use of software that field engineers say they accept on
their programs, so this builds the document a maintenance engineer would
otherwise write by hand: blocks, variables, where each one is read and written,
the I/O list, the call graph, the change history when a baseline exists, and —
given an endpoint — which configured point is which program address.

Deterministic by construction: no clock, no randomness, no LLM, no network. The
same export, store and config produce the same bytes, so two copies of the
document can be diffed. Everything that came out of the file is escaped (a
comment is whatever somebody typed). It reads the program and never writes it.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain.plc_program import field_logix, field_scan, field_xref
from iaiops.core.brain.plc_program.awl_parser import parse_awl
from iaiops.core.brain.plc_program.doc_sections import (
    field_section,
    rows_table,
    section,
)
from iaiops.core.brain.plc_program.fingerprint import content_sha256
from iaiops.core.brain.plc_program.l5x_parser import parse_l5x
from iaiops.core.brain.plc_program.outline import load_program
from iaiops.core.brain.plc_program.st_parser import parse_st
from iaiops.core.brain.plc_program.xref import _awl_hits, _st_hits
from iaiops.core.report.html import document, escape, kv

MAX_XREF_SYMBOLS = 200
MAX_SITES_PER_SYMBOL = 30
_PARSERS = {"scl": parse_st, "awl": parse_awl, "l5x": parse_l5x}
_IO_AREAS = ("I", "Q", "PI", "PQ")


def _header(source_file: str, fmt: str, sha: str, outline: Any) -> str:
    from iaiops import __version__

    tiles = "".join(
        [
            kv("Format", fmt),
            kv("Blocks", len(outline.blocks)),
            kv("Variables", sum(len(b.variables) for b in outline.blocks)),
            kv("Lines", outline.line_count),
            kv("Comments", outline.comment_count),
            kv("Parse errors", len(outline.parse_errors)),
        ]
    )
    return (
        f"<h1>Program document</h1><p class='sub mono'>{escape(source_file)}</p>"
        f"<p class='sub'>SHA-256 <span class='mono'>{escape(sha)}</span> · "
        f"iaiops {escape(__version__)}</p><dl class='grid card'>{tiles}</dl>"
    )


def _blocks(outline: Any) -> str:
    rows = [
        [
            b.name,
            b.kind,
            b.language,
            f"{b.line}–{b.end_line}",
            len(b.variables),
            len(b.calls),
            b.comment,
        ]
        for b in outline.blocks
    ]
    cols = ["Block", "Kind", "Language", "Lines / rungs", "Variables", "Calls", "Comment"]
    return section("Blocks", rows_table(cols, rows, empty="No blocks were extracted."))


def _variables(outline: Any) -> str:
    rows = [
        [b.name, v.name, v.var_type, v.section, v.line or "", v.comment]
        for b in outline.blocks
        for v in b.variables
    ]
    cols = ["Block", "Name", "Type", "Section", "Line", "Comment"]
    empty = (
        "No declarations are extracted from this format (AWL carries operands, not a "
        "declaration table) — see the cross-reference below."
        if outline.fmt == "awl"
        else "No variable declarations were found in this export."
    )
    return section("Variables", rows_table(cols, rows, empty=empty))


def _symbol_names(outline: Any) -> list[str]:
    seen: dict[str, None] = {}
    for block in outline.blocks:
        for var in block.variables:
            if var.name:
                seen.setdefault(var.name, None)
    return list(seen)


def _l5x_rows(text: str, path: str, outline: Any) -> tuple[list, int]:
    """Scope-aware tag sites from one pass over the rungs (AOI parameters excluded)."""
    tags = field_logix.logix_tags(outline)
    try:
        index = field_logix.site_index(text, path)
    except ValueError:
        return [], len(tags)
    local = {t.name.casefold(): set() for t in tags}
    for t in tags:
        if t.program:
            local[t.name.casefold()].add(t.program)
    rows = []
    for tag in tags[:MAX_XREF_SYMBOLS]:
        for site in field_logix.sites_for(tag, index, local[tag.name.casefold()])[
            :MAX_SITES_PER_SYMBOL
        ]:
            rows.append(
                [tag.path, site["access"], site["block"], site["line"], site["source_line"]]
            )
    return rows, len(tags)


def _xref_rows(
    path: str, text: str, fmt: str, outline: Any, scan: field_scan.S7Scan | None
) -> tuple[list, str]:
    if fmt == "l5x":
        rows, total = _l5x_rows(text, path, outline)
    else:
        rows, lines = [], text.splitlines()
        names = _symbol_names(outline)
        total = len(names)
        hits_for = _awl_hits if fmt == "awl" else _st_hits
        for name in names[:MAX_XREF_SYMBOLS]:
            for hit in hits_for(lines, name, path)[:MAX_SITES_PER_SYMBOL]:
                rows.append([name, hit.access, hit.block, hit.line, hit.source_line])
    if scan is not None:
        for site in scan.addresses:
            rows.append([site.address.text, site.access, site.block, site.line, site.source_line])
    note = ""
    if total > MAX_XREF_SYMBOLS:
        note = f"First {MAX_XREF_SYMBOLS} of {total} declared names cross-referenced."
    return rows, note


def _xref(path: str, text: str, fmt: str, outline: Any, scan: field_scan.S7Scan | None) -> str:
    rows, note = _xref_rows(path, text, fmt, outline, scan)
    cols = ["Symbol / address", "Access", "Block", "Line / rung", "Source"]
    lead = (
        "<p class='sub'>Access is classified from the statement (assignment target, AWL "
        "op, ladder output instruction) — a heuristic, not a data-flow analysis.</p>"
    )
    tail = f"<p class='sub'>{escape(note)}</p>" if note else ""
    return section(
        "Cross-reference", lead + rows_table(cols, rows, empty="Nothing to cross-reference.") + tail
    )


def _io_list(fmt: str, scan: field_scan.S7Scan | None) -> str:
    if scan is None:
        why = {
            "l5x": "The L5X parser does not extract I/O module configuration, so no I/O "
            "list is derived — module tags are not guessed from names.",
            "st": "A generic .st export is not read as Siemens addressing, so no I/O list "
            "is derived from its direct addresses.",
        }.get(fmt, "No I/O list for this format.")
        return section("I/O list", f"<p class='empty'>{escape(why)}</p>")
    by_address: dict[str, list] = {}
    for site in scan.addresses:
        if site.address.area in _IO_AREAS:
            by_address.setdefault(site.address.text, []).append(site)
    rows = [
        [
            text,
            "input" if sites[0].address.area in ("I", "PI") else "output",
            ", ".join(sorted({s.access for s in sites})),
            ", ".join(str(s.line) for s in sites[:10]),
        ]
        for text, sites in by_address.items()
    ]
    cols = ["Address", "Direction", "Access", "Lines"]
    empty = "No absolute I/O operands in this export (symbolic I/O lives in the tag table)."
    return section("I/O list", rows_table(cols, rows, empty=empty))


def _calls(outline: Any) -> str:
    rows = [[e.caller, e.callee, e.line] for e in outline.call_edges]
    return section(
        "Call graph", rows_table(["Caller", "Callee", "Line / rung"], rows, empty="No calls.")
    )


def _history(path: str, name: str | None) -> str:
    from iaiops.core.brain import program_baseline as pb

    try:
        hist = pb.history(name or pb._default_name(_as_path(path)))
    except LookupError:
        body = (
            "<p class='empty'>No snapshot recorded for this program — take one of the "
            "version you consider approved with <span class='mono'>iaiops program "
            "snapshot</span>, and this section will show what moved since.</p>"
        )
        return section("Change history", body)
    keyed = (
        "<p class='sub'>History is keyed by program name (default: the file stem — pass "
        "<span class='mono'>--name</span> when two programs share a file name).</p>"
    )
    rows = [
        [s.get("snapshot_id"), s.get("taken_at"), s.get("label"), s.get("note")]
        for s in hist["snapshots"]
    ]
    table = rows_table(["Snapshot", "Taken at", "Label", "Note"], rows, empty="")
    try:
        drift = pb.check_drift(path, name=name)
        verdict = (
            f"<p>This file against snapshot <span class='mono'>"
            f"{escape(drift['baseline']['snapshot_id'])}</span>: "
            f"<span class='badge'>{escape(drift['verdict'])}</span></p>"
        )
    except (LookupError, ValueError) as exc:
        verdict = f"<p class='empty'>Drift not computed: {escape(exc)}</p>"
    return section("Change history", keyed + table + verdict)


def _as_path(path: str):
    from pathlib import Path

    return Path(path).expanduser()


def render(path: str, *, target: Any = None, name: str | None = None) -> str:
    """The whole document for one export (and optionally one endpoint)."""
    resolved, text, raw_fmt = load_program(path)
    fmt = field_xref.program_format(resolved, raw_fmt)
    outline = _PARSERS[raw_fmt](text, str(resolved))
    scan = None
    if fmt == "awl":
        scan = field_scan.scan_awl(text)
    elif fmt == "scl":
        scan = field_scan.scan_scl(text)
    parts = [
        _header(str(resolved), fmt, content_sha256(text), outline),
        _blocks(outline),
        _variables(outline),
        _io_list(fmt, scan),
        _xref(str(resolved), text, raw_fmt, outline, scan),
        _calls(outline),
        _history(str(resolved), name),
    ]
    if target is not None:
        parts.append(field_section(field_xref.xref_program_endpoint(str(resolved), target)))
    if outline.parse_errors:
        rows = [[e] for e in outline.parse_errors]
        parts.append(section("Parse errors", rows_table(["Message"], rows, empty="")))
    footer = (
        "Structural extraction from an exported file — not a full grammar, not a live "
        "upload. No LLM was used to produce this document, and the program file was "
        "only read. Same inputs, same bytes."
    )
    return document(
        title=f"Program document — {resolved.name}", body="\n".join(parts), footer=escape(footer)
    )


__all__ = ["MAX_XREF_SYMBOLS", "render"]
