"""Cases — what the tool said, what a person said, and which of those may teach it.

This closes the loop ``rca_weights.learn_cause_weights`` has been waiting for.
The learner already existed; its corpus could only be IMPORTED — from a CMMS
export or a hand-written JSON file — so the tool could run at a site for two
years and stay exactly as clever as on day one.

Two hazards shape the design, and both are the tool fooling itself.

**Anchoring.** A person picking a cause from OUR ranked list gives a usable label
but not an independent one. Feed enough anchored labels back into the weights and
the system converges on whatever it already believed, growing more confident and
less correct. So the capture mode is recorded per case, agreement is reported per
mode, and an unusually HIGH agreement rate is a WARNING rather than a triumph: on
a real plant, a tool that agrees with the expert 95% of the time is more likely
to be leading them than to be right.

**Inference from the audit trail.** ``~/.iaiops/audit.db`` reliably records what
someone DID after a stoppage — that part is a recorded fact and costs nobody a
keystroke. What the action implies about the CAUSE is a guess. So the audit trail
yields ``suggested`` facts awaiting confirmation, never labels, which is exactly
what the provenance model in :mod:`iaiops.core.knowledge.model` is for.

[PURE] No I/O — the caller supplies audit rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from iaiops.core.knowledge.model import SUGGESTED, Fact

#: A person named the cause without being shown our ranking. Strongest.
STATED = "stated"
#: A person rejected our top hypothesis and named a different cause. Strong —
#: they disagreed, so nothing we said anchored the answer.
OVERRIDE = "override"
#: A person picked from our ranked list. Usable, but ANCHORED.
CONFIRMED = "confirmed"
#: Derived from what someone did afterwards. NOT a label.
INFERRED = "inferred"

CAPTURE_MODES = (STATED, OVERRIDE, CONFIRMED, INFERRED)

#: Modes that may train the weights.
EVIDENCE_MODES = frozenset({STATED, OVERRIDE, CONFIRMED})
#: Modes whose label was shaped by our own output.
ANCHORED_MODES = frozenset({CONFIRMED})

#: Agreement above this is reported as a warning.
HIGH_AGREEMENT_WARN = 90.0
#: Below this many cases, an agreement rate says nothing either way.
MIN_CASES_FOR_WARNING = 20

#: Audit rows at or above this risk level are treated as actions taken, not looking.
FIX_RISK_LEVELS = frozenset({"high", "critical"})

#: How a dismissal is recognised in a case's note. Named because three places
#: were matching the same bare string and a fourth invented its own rule.
DISMISSED_MARKER = "dismissed"


@dataclass(frozen=True)
class Case:
    """One incident: what we ranked, what a person concluded, what they did."""

    incident_id: str
    when: str
    #: Cause labels our ranking pointed at, best first.
    ranked: tuple[str, ...] = ()
    #: The confirmed cause. Empty when nobody has concluded anything.
    label: str = ""
    capture: str = ""
    #: Governed actions taken after the incident, straight from the audit log.
    fix_actions: tuple[dict[str, Any], ...] = ()
    note: str = field(default="")

    def __post_init__(self) -> None:
        if self.capture and self.capture not in CAPTURE_MODES:
            raise ValueError(
                f"Unknown capture mode {self.capture!r}. Allowed: {', '.join(CAPTURE_MODES)}."
            )
        if self.label and not self.capture:
            raise ValueError(
                f"Case {self.incident_id!r} has a label but no capture mode. HOW a cause "
                "was obtained decides whether it may train the weights — a label whose "
                "origin is unknown cannot be trusted to be independent."
            )

    @property
    def counts_as_evidence(self) -> bool:
        """Whether this case may train the cause weights."""
        return bool(self.label) and self.capture in EVIDENCE_MODES

    @property
    def answered(self) -> bool:
        """Whether a person has already said something about this case.

        A label, or a dismissal — both cost somebody a decision, and both are the
        thing re-detecting the same stoppage must never overwrite. One definition
        so ``list_cases(pending_only=True)`` and ``open_case``'s no-overwrite
        guard cannot drift apart; the guard's first version invented its own,
        matched every case that merely had a NOTE, and so silently stopped
        refreshing the pending ones it was supposed to leave alone.
        """
        return bool(self.label) or DISMISSED_MARKER in self.note.lower()

    @property
    def anchored(self) -> bool:
        """Whether our own ranking shaped the label."""
        return self.capture in ANCHORED_MODES

    @property
    def agreed(self) -> bool:
        """Whether the person's cause matched our top hypothesis."""
        return bool(self.label) and bool(self.ranked) and self.label == self.ranked[0]

    def as_fact(self) -> Fact:
        """This case as a knowledge-base fact.

        Always ``suggested``: even a stated cause is one site's account of one
        incident, and it enters the base as something a person can confirm
        rather than as settled truth.
        """
        return Fact(
            kind="case",
            key=f"case.{self.incident_id}",
            value={
                "when": self.when,
                "label": self.label,
                "capture": self.capture,
                "ranked": list(self.ranked),
                "fix_actions": [dict(a) for a in self.fix_actions],
            },
            source=SUGGESTED,
            note=self.note,
        )


def _parse(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def case_from_audit(
    incident_id: str,
    incident_ts: str,
    audit_rows: Any,
    window_s: float = 3600.0,
) -> Case:
    """Build a case from what someone actually DID after an incident.

    Zero extra typing: these actions already happened and were already recorded,
    which is the point — "operators will record the cause" is the most documented
    failure mode in this category, so the label has to be a byproduct of work
    already being done (D22).

    Only successful, high-risk actions count. A read is looking, not fixing; a
    failed write changed nothing and would misrepresent the response. The result
    carries NO label — what the action implies about the cause is for a person.
    """
    onset = _parse(incident_ts)
    actions: list[dict[str, Any]] = []
    for row in audit_rows or ():
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")) != "ok":
            continue
        if str(row.get("risk_level", "")) not in FIX_RISK_LEVELS:
            continue
        at = _parse(row.get("ts"))
        if onset is None or at is None or at < onset:
            continue
        if (at - onset).total_seconds() > window_s:
            continue
        actions.append(
            {
                "ts": str(row.get("ts", "")),
                "tool": str(row.get("tool", "")),
                "params": str(row.get("params", "")),
                "user": str(row.get("user", "")),
                "approved_by": str(row.get("approved_by", "")),
            }
        )
    actions.sort(key=lambda a: a["ts"])
    return Case(
        incident_id=incident_id,
        when=incident_ts,
        fix_actions=tuple(actions),
        capture=INFERRED if actions else "",
        note=(
            "Actions taken after the incident, from the audit trail. What they imply "
            "about the CAUSE is not recorded here — that is for a person to say."
        ),
    )


def to_corpus(cases: Any, include_anchored: bool = True) -> list[dict[str, Any]]:
    """``[{cause, signals}]`` for ``learn_cause_weights`` — evidence cases only.

    ``include_anchored=False`` trains on independent labels alone, so a site can
    check whether its weights survive without the ones its own tool shaped —
    without deleting its history to find out.
    """
    corpus: list[dict[str, Any]] = []
    for item in cases or ():
        if not isinstance(item, Case) or not item.counts_as_evidence:
            continue
        if item.anchored and not include_anchored:
            continue
        corpus.append({"cause": item.label, "signals": list(item.ranked)})
    return corpus


def agreement_report(cases: Any) -> dict[str, Any]:
    """How often a person agreed with us, and how much of that was anchored.

    High agreement is reported as a WARNING, not a score. A tool that agrees with
    the expert almost always on a real plant is more likely to be leading them,
    and the resulting weights would drift toward whatever it already believed.
    """
    evidence = [c for c in (cases or ()) if isinstance(c, Case) and c.counts_as_evidence]
    total = len(evidence)
    if not total:
        return {
            "n_cases": 0,
            "agreement_pct": None,
            "anchored_pct": None,
            "by_capture": {},
            "warn_above_pct": HIGH_AGREEMENT_WARN,
            "warning": "",
            "note": "No evidence cases yet — nothing to report either way.",
        }

    agreed = sum(1 for c in evidence if c.agreed)
    anchored = sum(1 for c in evidence if c.anchored)
    by_capture: dict[str, int] = {}
    for item in evidence:
        by_capture[item.capture] = by_capture.get(item.capture, 0) + 1

    agreement_pct = round(100.0 * agreed / total, 2)
    warning = ""
    if total >= MIN_CASES_FOR_WARNING and agreement_pct > HIGH_AGREEMENT_WARN:
        warning = (
            f"Agreement is {agreement_pct:g}% over {total} cases, above the "
            f"{HIGH_AGREEMENT_WARN:g}% mark. On a real plant that is more likely to mean "
            "the ranking is ANCHORING whoever confirms it than that it is that accurate. "
            "Prefer independently stated causes, and check whether the weights survive "
            "training without the anchored ones."
        )

    return {
        "n_cases": total,
        "agreement_pct": agreement_pct,
        "anchored_pct": round(100.0 * anchored / total, 2),
        "by_capture": by_capture,
        "warn_above_pct": HIGH_AGREEMENT_WARN,
        "min_cases_for_warning": MIN_CASES_FOR_WARNING,
        "warning": warning,
    }


__all__ = [
    "Case",
    "case_from_audit",
    "to_corpus",
    "agreement_report",
    "STATED",
    "OVERRIDE",
    "CONFIRMED",
    "INFERRED",
    "CAPTURE_MODES",
    "EVIDENCE_MODES",
    "ANCHORED_MODES",
    "HIGH_AGREEMENT_WARN",
    "MIN_CASES_FOR_WARNING",
]
