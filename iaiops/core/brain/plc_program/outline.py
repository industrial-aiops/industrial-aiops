"""Format sniffing, path validation and the unified program outline (A8).

Operates on **exported program text files only** — never a live PLC upload.
Advisory, extraction-based: every returned element cites ``source_file`` +
``line`` (rung number for L5X ladder) so the consuming agent quotes real
locations instead of hallucinating them.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from iaiops.core.brain.plc_program.awl_parser import parse_awl
from iaiops.core.brain.plc_program.l5x_parser import parse_l5x, rung_texts
from iaiops.core.brain.plc_program.model import Block, ProgramOutline
from iaiops.core.brain.plc_program.st_parser import parse_st
from iaiops.core.runtime.envelope import envelope_fields

ALLOWED_EXTENSIONS = frozenset({".st", ".scl", ".awl", ".l5x", ".txt"})
MAX_FILE_BYTES = 5 * 1024 * 1024  # exported program text; anything bigger is suspect
MAX_SECTION_LINES = 200

_AWL_HINTS = ("NETWORK", "CALL ", "END_ORGANIZATION_BLOCK")


def validate_program_path(path: str) -> Path:
    """Validate the user-passed file path; returns the resolved Path.

    Rules: must exist, must be a regular file (never a directory — no
    directory walking), extension in the allowlist, size ≤ 5 MB. The path is
    resolved (symlinks/.. collapsed) so exactly one file is ever read.
    """
    if not path or not str(path).strip():
        raise ValueError("path is required")
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"path not found: {path} ({exc})") from exc
    if not resolved.is_file():
        raise ValueError(f"not a file (directories are not walked): {resolved}")
    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(f"unsupported extension '{resolved.suffix}' — expected one of: {allowed}")
    size = resolved.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"file too large ({size} bytes > {MAX_FILE_BYTES}); split the export")
    return resolved


def sniff_format(path: Path, text: str) -> str:
    """Best-effort format detection: extension first, then content."""
    suffix = path.suffix.lower()
    if suffix in (".st", ".scl"):
        return "scl"
    if suffix == ".awl":
        return "awl"
    if suffix == ".l5x":
        return "l5x"
    head = text.lstrip()[:2000]
    if head.startswith("<?xml") or "<RSLogix5000Content" in head:
        return "l5x"
    upper = text[:20_000].upper()
    if any(hint in upper for hint in _AWL_HINTS) and ":=" not in upper:
        return "awl"
    return "scl"


def load_program(path: str) -> tuple[Path, str, str]:
    """Validate ``path``, read it, and sniff its format → (path, text, fmt)."""
    resolved = validate_program_path(path)
    text = resolved.read_text("utf-8", errors="replace")
    return resolved, text, sniff_format(resolved, text)


def outline_program(path: str) -> ProgramOutline:
    """Unified structural outline of one exported program file."""
    resolved, text, fmt = load_program(path)
    parser = {"scl": parse_st, "awl": parse_awl, "l5x": parse_l5x}[fmt]
    return parser(text, str(resolved))


def outline_stats(outline: ProgramOutline) -> dict:
    """Cheap summary counters for the agent's first orientation pass."""
    return {
        "blocks": len(outline.blocks),
        "variables": sum(len(b.variables) for b in outline.blocks),
        "call_edges": len(outline.call_edges),
        "branches": sum(len(b.branches) for b in outline.blocks),
        "timers_counters": sum(len(b.timers_counters) for b in outline.blocks),
        "comments": outline.comment_count,
        "lines": outline.line_count,
        "parse_errors": len(outline.parse_errors),
    }


def outline_to_bounded_dict(
    outline: ProgramOutline, max_blocks: int = 50, max_vars_per_block: int = 100
) -> dict:
    """JSON-safe outline with hard caps + explicit truncation flags."""
    blocks = []
    for blk in outline.blocks[:max_blocks]:
        d = asdict(blk)
        d["variables"] = d["variables"][:max_vars_per_block]
        d["variables_truncated"] = len(blk.variables) > max_vars_per_block
        blocks.append(d)
    return {
        "source_file": outline.source_file,
        "format": outline.fmt,
        "stats": outline_stats(outline),
        "blocks": blocks,
        "blocks_truncated": len(outline.blocks) > max_blocks,
        "call_graph": [asdict(e) for e in outline.call_edges[: max_blocks * 20]],
        "parse_errors": list(outline.parse_errors),
        "citation_note": (
            "line = 1-based file line (rung number for L5X ladder); always cite "
            "source_file:line when explaining this program."
        ),
    }


def _find_block(outline: ProgramOutline, name: str) -> Block | None:
    wanted = name.strip().strip('"').lower()
    for blk in outline.blocks:
        if blk.name.lower() == wanted or blk.name.lower().endswith("." + wanted):
            return blk
    return None


def block_section(path: str, block: str, max_lines: int = MAX_SECTION_LINES) -> dict:
    """Return one named block's source text (capped) with its line span.

    For text formats this slices the file between the block's header and END_*
    lines; for L5X it reconstructs the routine's rungs (``[rung N] text``).
    """
    resolved, text, fmt = load_program(path)
    parser = {"scl": parse_st, "awl": parse_awl, "l5x": parse_l5x}[fmt]
    outline = parser(text, str(resolved))
    blk = _find_block(outline, block)
    if blk is None:
        names = [b.name for b in outline.blocks][:50]
        raise ValueError(f"block '{block}' not found. Available blocks: {names}")

    if fmt == "l5x":
        rows = [
            f"[rung {num}] {(('// ' + comment + ' ') if comment else '')}{rtext}"
            for bname, num, rtext, comment in rung_texts(text, str(resolved))
            if bname == blk.name
        ]
        total_lines = len(rows)
        truncated = total_lines > max_lines
        source = "\n".join(rows[:max_lines])
    else:
        lines = text.splitlines()
        start, end = max(blk.line - 1, 0), min(blk.end_line, len(lines))
        span = lines[start:end]
        total_lines = len(span)
        truncated = total_lines > max_lines
        source = "\n".join(span[:max_lines])

    return {
        "source_file": str(resolved),
        "format": fmt,
        "block": blk.name,
        "kind": blk.kind,
        "start_line": blk.line,
        "end_line": blk.end_line,
        "lines_returned": min(max_lines, source.count("\n") + 1 if source else 0),
        "truncated": truncated,  # legacy bool — see `is_truncated`
        "source": source,
        "parse_errors": list(outline.parse_errors),
        # "Items" here are SOURCE LINES, not list rows — the contract is the
        # same: how many came back, how many exist, was anything cut.
        **envelope_fields(returned=min(total_lines, max_lines), total=total_lines),
    }
