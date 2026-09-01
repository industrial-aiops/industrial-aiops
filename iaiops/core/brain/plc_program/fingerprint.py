"""Structural fingerprints of an exported PLC program — the basis for drift.

A control program is a controlled document. In a regulated plant an undocumented
change to one is a change-control finding before it is anything else, and the
usual way of noticing is that somebody remembers. This module gives the
comparison a number.

**What is in a block's fingerprint**, and therefore what counts as a logic
change: the block's name, kind and language, its declared variables (name, type,
section), the blocks it calls, its branch conditions, and its timers/counters.

**What is deliberately not**: line numbers, comments, and the order blocks appear
in the file. Adding a comment at the top of a file shifts every line number in
it; a fingerprint that moved would report the whole program as changed and be
switched off within a week.

**And what that costs.** These parsers are regex/line/XML extraction, honest
about it in their own docstrings — not a grammar. Two programs with the same
fingerprints are *not* proven equivalent: something can change inside a construct
the parser does not model. So the file's own SHA-256 is carried beside the
structure and it, not the fingerprint, decides whether anything changed at all.
Matching fingerprints over differing bytes is reported as *changed outside the
extracted structure* — never as "documentation only", and never as a clearance.
That distinction is the whole reason to be careful here: the comfortable answer
is that nothing important changed, and it is the answer that gets someone hurt.
"""

from __future__ import annotations

import hashlib
from typing import Any

from iaiops.core.brain.plc_program.model import Block, ProgramOutline

#: Bumped when the fingerprint recipe changes. A stored snapshot at a different
#: recipe cannot be compared with one taken now — the comparison would report
#: drift that is an artefact of this module, which is the worst kind of false
#: positive: it teaches the reader to ignore the tool.
RECIPE_VERSION = 1


def _digest(parts: list[str]) -> str:
    joined = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


def _variable_parts(block: Block) -> list[str]:
    # Sorted: a declaration moved within its VAR section is not a change.
    return sorted(f"var|{v.section}|{v.name}|{v.var_type}" for v in block.variables)


def _call_parts(block: Block) -> list[str]:
    # Sorted, and duplicates kept — calling a block twice is not calling it once.
    return sorted(f"call|{c.callee}" for c in block.calls if c.callee)


def _branch_parts(block: Block) -> list[str]:
    return sorted(f"branch|{b.kind}|{b.condition}" for b in block.branches)


def _timer_parts(block: Block) -> list[str]:
    return sorted(f"timer|{t.kind}|{t.name}" for t in block.timers_counters)


def block_facts(block: Block) -> dict[str, list[str]]:
    """The block's fingerprinted facts, by category — what a diff names."""
    return {
        "variables": _variable_parts(block),
        "calls": _call_parts(block),
        "branches": _branch_parts(block),
        "timers_counters": _timer_parts(block),
    }


def block_fingerprint(block: Block) -> str:
    """SHA-256 over one block's logic-bearing structure."""
    facts = block_facts(block)
    parts = [f"block|{block.name}|{block.kind}|{block.language}"]
    for category in ("variables", "calls", "branches", "timers_counters"):
        parts.extend(facts[category])
    return _digest(parts)


def _block_keys(outline: ProgramOutline) -> list[tuple[str, Block]]:
    """Stable keys for the blocks, disambiguating repeated names.

    A name collision is rare and a silently dropped block is not acceptable, so
    the second occurrence becomes ``NAME#2`` rather than overwriting the first.
    """
    seen: dict[str, int] = {}
    keyed: list[tuple[str, Block]] = []
    for block in outline.blocks:
        name = block.name or "(unnamed)"
        seen[name] = seen.get(name, 0) + 1
        keyed.append((name if seen[name] == 1 else f"{name}#{seen[name]}", block))
    return keyed


def fingerprint_outline(outline: ProgramOutline) -> dict[str, Any]:
    """Per-block fingerprints plus the structural totals a diff reports.

    Storable: no source text, no declaration names — hashes and counts only.
    """
    keyed = _block_keys(outline)
    blocks = {
        key: {
            "fingerprint": block_fingerprint(block),
            "kind": block.kind,
            "language": block.language,
            "line": block.line,
            # Per-category digests rather than the facts themselves. A stored
            # snapshot then costs four short hashes per block instead of every
            # declaration in the program, and a drift can still say WHICH KIND of
            # thing changed. Saying *what* changed needs the file, and whoever is
            # asking has it — they are standing in front of it.
            "facts_digest": {
                category: _digest(parts)[:16] for category, parts in block_facts(block).items()
            },
        }
        for key, block in keyed
    }
    return {
        "recipe_version": RECIPE_VERSION,
        "fmt": outline.fmt,
        "block_count": len(keyed),
        "line_count": outline.line_count,
        "comment_count": outline.comment_count,
        "parse_errors": list(outline.parse_errors),
        "blocks": blocks,
        "structure_fingerprint": _digest(
            [f"{key}|{blocks[key]['fingerprint']}" for key in sorted(blocks)]
        ),
    }


def content_sha256(text: str) -> str:
    """The file's own digest — the only thing that decides *whether* it changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "RECIPE_VERSION",
    "block_facts",
    "block_fingerprint",
    "content_sha256",
    "fingerprint_outline",
]
