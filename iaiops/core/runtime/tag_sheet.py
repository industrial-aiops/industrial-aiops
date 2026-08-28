"""Point-list semantic confirmation as a table — export, edit, apply.

HLD §10.1 named this and then nobody built it: *point-list confirmation is
naturally a table (tens to hundreds of rows to tick or re-categorise); the CLI
need only export a CSV, let a person edit it, and import it back.* The App page
was ordered "after" — but **this, the CLI fallback it was meant to rest on, did
not exist either.** Until now the only way to say "this tag is the production
counter" was hand-editing ``role:`` in config.yaml, which is exactly the method
§10.1 says stops working at a hundred rows.

That is what "the semantic layer still has to come from a person" has really been
blocked on. Not a design gap — **no usable way to supply it.**

**Why this emits a config patch instead of storing its own declarations.** The
first version stored roles as ``declared`` facts with an author, like ``relations
declare`` and ``knowledge mount``. It was wrong here, and the reason is a
coupling: ``oee measure`` reads ``role`` off the config tag OBJECTS, and
``MonitorTag`` refuses a ``run_state`` that does not also declare
``running_when``. A parallel store would therefore have let ``readiness`` report
the mapping as met while ``oee measure`` still could not run — the exact
flattering error this product keeps having to remove. config.yaml stays the one
source of truth; this only fixes the ergonomics of editing it.

The refusals, in order of how much damage each would do:

1. **It never suggests a role.** Inferring one from a tag NAME is the most
   tempting inference here and the one D16 forbids: a wrong production counter
   yields a plausible OEE, which is worse than an error. A plant with a
   ``GoodPartsCounter`` that counts something else is ordinary.
2. **``run_state`` without ``running_when`` is refused.** Assuming "anything
   non-zero means running" counts idle and fault as production — the trap
   ``MonitorTag`` already refuses, refused here too so the sheet cannot emit a
   patch that config would then reject.
3. **A ref nobody monitors is refused.** A typo would otherwise put a role on a
   tag that is not collected.
4. **All or nothing**, and a role claimed twice is refused — the rule
   ``roles_present`` already applies: picking either is a guess, and the wrong
   pick produces a number that looks right.

[PURE] No I/O and no clock. Rows in, rows or text out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from iaiops.core.brain._shared import s

MAX_NAME = 160
#: A point list longer than this is not one somebody confirms by hand.
MAX_ROWS = 5000

#: The header is a contract with whatever the site opens the file in. ``role`` and
#: ``running_when`` are the columns a person edits; ``declared_role`` is read-only
#: context.
SHEET_COLUMNS = ("endpoint", "ref", "label", "declared_role", "role", "running_when")

__all__ = ["SHEET_COLUMNS", "TagEdit", "sheet_rows", "validate_rows", "config_patch"]


@dataclass(frozen=True)
class TagEdit:
    """One confirmed row: this tag, on this endpoint, means this."""

    endpoint: str
    ref: str
    role: str
    running_when: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "ref": self.ref,
            "role": self.role,
            "running_when": list(self.running_when),
        }


def _attr(tag: Any, name: str) -> str:
    """Duck-typed, like ``roles_present``: a hand-written config's tags may never
    have become ``MonitorTag`` objects, and this has to survive that."""
    value = getattr(tag, name, None)
    if value is None and isinstance(tag, dict):
        value = tag.get(name)
    return str(value or "")


def sheet_rows(config: Any) -> tuple[dict[str, str], ...]:
    """One row per monitored tag, with the ``role`` column deliberately EMPTY.

    ``declared_role`` shows what config.yaml already says, so the reader can see
    it without it being pre-filled: copying it into ``role`` would make
    re-applying an untouched sheet re-declare everything, and a no-op would read
    as a confirmation. The same holds for ``running_when`` — everything already
    declared is read-only context here, everything editable starts empty.
    """
    rows: list[dict[str, str]] = []
    for target in getattr(config, "targets", ()) or ():
        endpoint = str(getattr(target, "name", ""))
        for tag in getattr(target, "tags", ()) or ():
            rows.append(
                {
                    "endpoint": endpoint,
                    "ref": _attr(tag, "ref"),
                    "label": _attr(tag, "label"),
                    "declared_role": _attr(tag, "role"),
                    "role": "",
                    # Empty for the same reason `role` is, and — found by looking
                    # at the rendered page — for consistency with it. Echoing the
                    # existing value into an EDITABLE cell while leaving `role`
                    # blank meant somebody who changed the role to a counter got
                    # refused over a field they never touched.
                    "running_when": "",
                }
            )
    return tuple(rows)


def validate_rows(rows: list[dict[str, Any]], config: Any = None) -> tuple[TagEdit, ...]:
    """Every filled row, checked. Raises rather than returning a partial answer.

    A blank ``role`` is skipped, not treated as a withdrawal: a sheet that has
    been through a spreadsheet loses cells routinely, and blank-means-withdraw
    would silently delete semantics somebody spent an afternoon on.
    """
    from iaiops.core.runtime.config import TagRole

    if len(rows or ()) > MAX_ROWS:
        raise ValueError(f"A confirmation sheet is capped at {MAX_ROWS} rows.")
    known = _known_refs(config)
    edits = [
        _edit(row, str(row.get("role", "") or "").strip().lower(), known, TagRole)
        for row in rows or ()
        if str(row.get("role", "") or "").strip()
    ]
    _refuse_double_claims(edits)
    return tuple(edits)


def config_patch(edits: tuple[TagEdit, ...], by: str = "") -> str:
    """The exact config.yaml edit, grouped by endpoint, ready to paste.

    Emitted rather than written: there is no config writer in this product, and a
    YAML round-trip would drop the comments a site wrote for itself. The author
    rides along as a comment because the file has no other place to record who
    decided that a given tag counts production.
    """
    if not edits:
        return ""
    lines: list[str] = []
    if by:
        lines.append(f"# tag semantics confirmed by {s(str(by).strip(), MAX_NAME)}")
    lines.append("# Merge into the matching `tags:` entries in config.yaml.")
    for endpoint in dict.fromkeys(e.endpoint for e in edits):
        lines.append(f"# --- {endpoint} ---")
        for edit in (e for e in edits if e.endpoint == endpoint):
            # Quoted via json.dumps (YAML 1.2 is a JSON superset), because a
            # Modbus ref like 40001 re-parses as an INT otherwise and then no
            # longer matches the string ref it is supposed to annotate. Found by
            # running the round trip, not by any assertion about the text.
            lines.append(f"  - ref: {json.dumps(edit.ref)}")
            lines.append(f"    role: {edit.role}")
            if edit.running_when:
                values = ", ".join(str(v) for v in edit.running_when)
                lines.append(f"    running_when: [{values}]")
    return "\n".join(lines) + "\n"


def _known_refs(config: Any) -> dict[str, set[str]] | None:
    """``{endpoint: {ref}}``, or None when there is no config to check against."""
    if config is None:
        return None
    return {
        str(getattr(t, "name", "")): {_attr(tag, "ref") for tag in getattr(t, "tags", ()) or ()}
        for t in getattr(config, "targets", ()) or ()
    }


def _edit(row: dict[str, Any], role: str, known: dict[str, set[str]] | None, roles: Any) -> TagEdit:
    endpoint = s(str(row.get("endpoint", "") or "").strip(), MAX_NAME)
    ref = s(str(row.get("ref", "") or "").strip(), MAX_NAME)
    if not ref:
        raise ValueError("Every confirmed row needs a `ref` — the tag it is about.")
    if role not in roles.ALL:
        raise ValueError(
            f"Unknown role {role!r} on {ref!r}. The vocabulary is deliberately "
            f"small: {', '.join(roles.ALL)}. It is not extended from a sheet."
        )
    if known is not None and ref not in known.get(endpoint, set()):
        raise ValueError(
            f"Nothing monitors {ref!r} on {endpoint or '(no endpoint)'!r}. Putting a role "
            "on a tag that is not collected would have readiness report the gap as "
            "filled while nothing fills it. Check the ref, or add the tag first."
        )
    running = tuple(str(row.get("running_when", "") or "").replace(",", " ").split())
    if role == roles.RUN_STATE and not running:
        raise ValueError(
            f"{ref!r} is declared run_state but `running_when` is empty — which value "
            "means RUNNING. Assuming 'anything non-zero' counts idle and fault as "
            "production and inflates availability. Example: running_when: 2"
        )
    if running and role != roles.RUN_STATE:
        raise ValueError(
            f"`running_when` only means something on a run_state tag; {ref!r} is {role}."
        )
    return TagEdit(endpoint=endpoint, ref=ref, role=role, running_when=running)


def _refuse_double_claims(edits: list[TagEdit]) -> None:
    seen: dict[str, str] = {}
    for edit in edits:
        if edit.role in seen and seen[edit.role] != edit.ref:
            raise ValueError(
                f"Two tags in this sheet both claim to be the {edit.role}: "
                f"{seen[edit.role]!r} and {edit.ref!r}. One line has one of these; picking "
                "either would be a guess, and the wrong pick produces a number that "
                "looks right."
            )
        seen[edit.role] = edit.ref
