"""Opening a case, and confirming it in one choice.

The loop was built before its entrance: cases, capture modes and the corpus that
feeds ``learn_cause_weights`` all existed, but nothing could CREATE a case. This
is the entrance — a stoppage becomes a case, the case waits for a person, and one
choice turns it into a label.

Two rules are easy to lose and expensive to lose.

**The capture mode is DERIVED, never declared by the person answering.** Whether
an answer was anchored depends on what we had already suggested, not on what the
answerer says about themselves. If anyone could mark their own answer "stated",
the anchoring guard would be defeated — and defeated silently, because the
agreement rate would still look healthy while the weights drifted toward whatever
the tool already believed.

**The cause comes from the taxonomy, not from a text box.** The reason
``maintenance_log.py`` needs painful synonym mapping is that CMMS free text says
"bearing failure", "网络中断" and "Fixed it" for things a learner cannot use. A
label captured at diagnosis time should arrive in the vocabulary the learner
already speaks — that is most of its advantage over a work order.

Storage is the site knowledge base: a case is a ``suggested`` fact keyed
``case.<id>``, so it inherits provenance and never becomes settled truth just by
being written down.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from iaiops.core.knowledge.cases import (
    CONFIRMED,
    OVERRIDE,
    Case,
    case_from_audit,
)
from iaiops.core.knowledge.model import KnowledgeBase
from iaiops.core.knowledge.store import load, save

_ID_SAFE = re.compile(r"[^A-Za-z0-9]+")


def _case_id(endpoint: str, when: str) -> str:
    """Stable and readable: two stoppages a second apart stay distinguishable."""
    stamp = _ID_SAFE.sub("", str(when))[:15]
    return f"{_ID_SAFE.sub('-', str(endpoint)).strip('-')}-{stamp}"


def _cases_from(kb: KnowledgeBase) -> list[Case]:
    out: list[Case] = []
    for fact in kb.facts:
        if fact.kind != "case" or not isinstance(fact.value, dict):
            continue
        value = fact.value
        out.append(
            Case(
                incident_id=str(fact.key).removeprefix("case."),
                when=str(value.get("when", "")),
                ranked=tuple(value.get("ranked") or ()),
                label=str(value.get("label", "")),
                capture=str(value.get("capture", "")),
                fix_actions=tuple(dict(a) for a in (value.get("fix_actions") or ())),
                note=fact.note,
            )
        )
    return out


def _store(site: str, case: Case, base_dir: Path | None) -> Case:
    """Write ``case`` into the site's base, replacing any earlier version."""
    kb = load(site, base_dir=base_dir)
    key = f"case.{case.incident_id}"
    kept = tuple(f for f in kb.facts if f.key != key)
    save(KnowledgeBase(site=kb.site, facts=kept + (case.as_fact(),)), base_dir=base_dir)
    return case


def open_case(
    site: str,
    endpoint: str,
    when: str,
    ranked: Any = (),
    audit_rows: Any = (),
    base_dir: Path | None = None,
) -> Case:
    """Open a case for a stoppage, carrying what we ranked and what someone did.

    The case starts with NO label: the actions in the audit trail are recorded
    facts, but what they imply about the cause is for a person to say.
    """
    case = case_from_audit(_case_id(endpoint, when), when, audit_rows)
    case = Case(
        incident_id=case.incident_id,
        when=when,
        ranked=tuple(str(r) for r in (ranked or ())),
        label="",
        capture=case.capture,
        fix_actions=case.fix_actions,
        note=case.note,
    )
    return _store(site, case, base_dir)


def list_cases(site: str, pending_only: bool = False, base_dir: Path | None = None) -> list[Case]:
    """Cases for a site, newest first. A site with none lists nothing."""
    cases = sorted(_cases_from(load(site, base_dir=base_dir)), key=lambda c: c.when, reverse=True)
    if pending_only:
        cases = [c for c in cases if not c.label and "dismissed" not in c.note.lower()]
    return cases


def _find(site: str, incident_id: str, base_dir: Path | None) -> Case:
    for case in _cases_from(load(site, base_dir=base_dir)):
        if case.incident_id == incident_id:
            return case
    raise KeyError(f"No case {incident_id!r} at site {site!r}.")


def confirm_case(
    site: str,
    incident_id: str,
    cause: str,
    by: str,
    base_dir: Path | None = None,
) -> Case:
    """Record the confirmed cause. ``cause`` must be in the learner's taxonomy.

    There is deliberately no ``capture`` parameter: whether the answer was
    anchored is decided by whether we had already suggested it, and letting the
    answerer declare it would make the anchoring measurement meaningless.
    """
    from iaiops.core.brain.rca_weights import LEARNABLE_CAUSES

    if not str(by).strip():
        raise ValueError(
            f"Confirming case {incident_id!r} needs to record WHO confirmed it — an "
            "unattributable label cannot be reviewed or withdrawn later."
        )
    if cause not in LEARNABLE_CAUSES:
        raise ValueError(
            f"Cause {cause!r} is not in the taxonomy. Allowed: "
            f"{', '.join(sorted(LEARNABLE_CAUSES))}. A label captured here should arrive "
            "in the vocabulary the learner already speaks — that is most of its advantage "
            "over a free-text work order."
        )

    case = _find(site, incident_id, base_dir)
    anchored = cause in case.ranked
    updated = Case(
        incident_id=case.incident_id,
        when=case.when,
        ranked=case.ranked,
        label=cause,
        capture=CONFIRMED if anchored else OVERRIDE,
        fix_actions=case.fix_actions,
        note=(
            f"confirmed by {str(by).strip()} — "
            + (
                "chosen from the ranking we offered, so this label is ANCHORED"
                if anchored
                else "a cause we did not rank, so this label is independent"
            )
        ),
    )
    return _store(site, updated, base_dir)


def dismiss_case(site: str, incident_id: str, by: str, base_dir: Path | None = None) -> Case:
    """Mark a case as not an incident. A negative label, and free.

    Dismissals cost the operator one keystroke and cost us nothing, which makes
    them the cheapest signal in the loop — and usually the most plentiful.
    """
    if not str(by).strip():
        raise ValueError(f"Dismissing case {incident_id!r} needs to record WHO dismissed it.")
    case = _find(site, incident_id, base_dir)
    updated = Case(
        incident_id=case.incident_id,
        when=case.when,
        ranked=case.ranked,
        label="",
        capture="",
        fix_actions=case.fix_actions,
        note=f"dismissed by {str(by).strip()} — not an incident; kept as a negative example",
    )
    return _store(site, updated, base_dir)


__all__ = ["open_case", "list_cases", "confirm_case", "dismiss_case"]
