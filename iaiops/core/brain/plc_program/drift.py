"""Compare two program fingerprints — what changed, and what cannot be claimed.

The verdict vocabulary is the point of this module, so it is small and each word
is load-bearing:

``identical``
    The two files have the same SHA-256. Nothing else earns this word.

``logic_changed``
    The extracted structure differs — a block appeared, disappeared, or its
    declarations / calls / branches / timers moved. Reported per block, naming
    the categories that differ.

``changed_outside_extracted_structure``
    The bytes differ and the structure does not. That is *usually* comments or
    formatting, and calling it "documentation only" would be the comfortable
    reading of evidence that does not support it: these parsers are regex / line
    / XML extraction, not grammars, so a real change inside a construct they do
    not model lands here too. The line and comment counts are reported beside it
    so a reviewer can see which way it leans, and the verdict still says look.

Nothing here clears a program. A drift report is a reason to go and read the
diff, and it is worded so that nobody mistakes it for having read it.
"""

from __future__ import annotations

from typing import Any

FACT_CATEGORIES = ("variables", "calls", "branches", "timers_counters")

VERDICT_IDENTICAL = "identical"
VERDICT_LOGIC_CHANGED = "logic_changed"
VERDICT_OUTSIDE_STRUCTURE = "changed_outside_extracted_structure"

_OUTSIDE_NOTE = (
    "The file changed but every extracted block fingerprint matched. That is "
    "usually comments or formatting — but these parsers extract structure, they "
    "do not parse a grammar, so a change inside a construct they do not model "
    "looks the same from here. Read the diff; this is not a clearance."
)
_IDENTICAL_NOTE = "Byte-identical to the compared snapshot."


class RecipeMismatchError(ValueError):
    """Raised when two fingerprints were taken with different recipes."""


def _block_changes(before: dict, after: dict) -> list[dict[str, Any]]:
    """Blocks present in both whose fingerprints differ, with the categories."""
    changes: list[dict[str, Any]] = []
    for key in sorted(set(before) & set(after)):
        b, a = before[key], after[key]
        if b.get("fingerprint") == a.get("fingerprint"):
            continue
        b_facts = b.get("facts_digest") or {}
        a_facts = a.get("facts_digest") or {}
        differing = [c for c in FACT_CATEGORIES if b_facts.get(c) != a_facts.get(c)]
        changes.append(
            {
                "block": key,
                "kind": a.get("kind") or b.get("kind") or "",
                "line": a.get("line"),
                "previous_line": b.get("line"),
                # A block whose kind or language changed differs without any
                # category differing — say so rather than printing an empty list.
                "changed": differing or ["block_identity"],
            }
        )
    return changes


def _listed(keys: set[str], source: dict) -> list[dict[str, Any]]:
    return [
        {"block": k, "kind": source[k].get("kind", ""), "line": source[k].get("line")}
        for k in sorted(keys)
    ]


def _totals(before: dict, after: dict) -> dict[str, Any]:
    return {
        field: {"before": before.get(field), "after": after.get(field)}
        for field in ("block_count", "line_count", "comment_count")
    }


def compare(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    before_sha256: str,
    after_sha256: str,
) -> dict[str, Any]:
    """Diff two :func:`~...fingerprint.fingerprint_outline` results.

    ``before_sha256`` / ``after_sha256`` are the files' own digests — they decide
    *whether* anything changed. The fingerprints only ever explain it.
    """
    if before.get("recipe_version") != after.get("recipe_version"):
        raise RecipeMismatchError(
            f"Fingerprint recipes differ (stored {before.get('recipe_version')}, "
            f"current {after.get('recipe_version')}). Comparing them would report "
            "drift that is an artefact of the tool. Re-take the baseline snapshot "
            "of the version you consider approved, then compare against that."
        )

    b_blocks = before.get("blocks") or {}
    a_blocks = after.get("blocks") or {}
    added = set(a_blocks) - set(b_blocks)
    removed = set(b_blocks) - set(a_blocks)
    changed = _block_changes(b_blocks, a_blocks)

    content_changed = before_sha256 != after_sha256
    structure_changed = bool(added or removed or changed)
    if not content_changed:
        verdict, note = VERDICT_IDENTICAL, _IDENTICAL_NOTE
    elif structure_changed:
        verdict, note = VERDICT_LOGIC_CHANGED, ""
    else:
        verdict, note = VERDICT_OUTSIDE_STRUCTURE, _OUTSIDE_NOTE

    return {
        "verdict": verdict,
        "content_changed": content_changed,
        "structure_changed": structure_changed,
        "content_sha256": {"before": before_sha256, "after": after_sha256},
        "blocks": {
            "added": _listed(added, a_blocks),
            "removed": _listed(removed, b_blocks),
            "changed": changed,
            "unchanged": len(set(a_blocks) & set(b_blocks)) - len(changed),
        },
        "totals": _totals(before, after),
        "parse_errors": {
            "before": list(before.get("parse_errors") or ()),
            "after": list(after.get("parse_errors") or ()),
        },
        "note": note,
        "advisory": (
            "Structural comparison of an EXPORTED program file. It reports what "
            "moved; deciding whether the change was authorised is change control's "
            "job, and this tool never touched the PLC."
        ),
    }


__all__ = [
    "FACT_CATEGORIES",
    "VERDICT_IDENTICAL",
    "VERDICT_LOGIC_CHANGED",
    "VERDICT_OUTSIDE_STRUCTURE",
    "RecipeMismatchError",
    "compare",
]
