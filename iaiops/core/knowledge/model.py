"""Facts a site accumulates, each carrying where it came from.

The knowledge base is what makes the product improve with use — relationships,
confirmed cases, learned weights. It is a RETENTION mechanism and not an entry
ticket (HLD D20): the product must be useful on a site whose base is empty, or
it becomes a thing customers must do unpaid data entry to switch on.

That makes provenance the load-bearing part rather than a nicety.

``declared``
    A human said so. Highest trust, and no evidence is required — "the process
    engineer told us" IS the evidence.
``derived``
    Computed from data, and it must be able to show the working. A derived fact
    nobody can check is a suggestion wearing a better label, so evidence is
    mandatory.
``suggested``
    A heuristic's guess. **Withheld from reasoning until a human confirms it** —
    withheld, not hidden: suggestions are the review queue.

The rule that matters: a ``suggested`` fact used as if it were ``declared`` makes
root-cause analysis confidently wrong, which is worse than no answer. And it
compounds — once one unconfirmed guess is treated as fact, everything downstream
inherits the error and nothing marks where it entered. This is D16's discipline
applied to something that accumulates for years rather than for one command.

Conflicts are reported, never resolved by preference. Higher trust supersedes
lower, but two humans contradicting each other is not something to average.

[PURE] No I/O — persistence lives in ``store.py``, following the
``baseline`` / ``baseline_store`` split.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

DECLARED = "declared"
DERIVED = "derived"
SUGGESTED = "suggested"

#: Most trusted first. Used to supersede, never to average.
TRUST_ORDER = (DECLARED, DERIVED, SUGGESTED)

#: Sources whose facts may take part in reasoning.
USABLE_SOURCES = frozenset({DECLARED, DERIVED})

_FORMAT_VERSION = 1


@dataclass(frozen=True)
class Fact:
    """One thing known about a site, and how it came to be known."""

    kind: str
    key: str
    value: Any
    source: str
    #: Why this is believed. Mandatory for ``derived``; meaningless for
    #: ``declared`` (a person is the evidence).
    evidence: str = ""
    #: Who confirmed a suggestion, when one was confirmed.
    confirmed_by_whom: str = ""
    #: What this fact's source was BEFORE confirmation, so an audit can ask
    #: "who agreed to this, and to what".
    was: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.source not in TRUST_ORDER:
            raise ValueError(
                f"Unknown provenance {self.source!r}. Allowed: {', '.join(TRUST_ORDER)}."
            )
        if not self.key:
            raise ValueError("A fact needs a key.")
        if self.source == DERIVED and not self.evidence:
            raise ValueError(
                f"Derived fact {self.key!r} carries no evidence. A derived fact nobody "
                "can check is a suggestion with a better label — record what it was "
                "computed from, or record it as 'suggested'."
            )

    @property
    def usable(self) -> bool:
        """Whether this may take part in reasoning."""
        return self.source in USABLE_SOURCES

    def confirmed_by(self, whom: str) -> Fact:
        """Promote a suggestion to ``declared``. Returns a NEW fact.

        Promotion happens by a human confirming and by nothing else — no
        threshold, no accumulation of agreement, no self-promotion after n
        sightings. Those would each be a way for the system to talk itself into
        believing its own guess.
        """
        if not str(whom).strip():
            raise ValueError(
                f"Confirming {self.key!r} needs to record WHO confirmed it — an "
                "unattributable confirmation cannot be reviewed or withdrawn."
            )
        return replace(
            self,
            source=DECLARED,
            was=self.source,
            confirmed_by_whom=str(whom).strip(),
        )

    def as_dict(self) -> dict[str, Any]:
        out = {
            "kind": self.kind,
            "key": self.key,
            "value": self.value,
            "source": self.source,
        }
        for name in ("evidence", "confirmed_by_whom", "was", "note"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> Fact:
        if not isinstance(raw, dict):
            raise ValueError(f"A fact must be an object, got {type(raw).__name__}.")
        return cls(
            kind=str(raw.get("kind", "")),
            key=str(raw.get("key", "")),
            value=raw.get("value"),
            source=str(raw.get("source", "")),
            evidence=str(raw.get("evidence", "")),
            confirmed_by_whom=str(raw.get("confirmed_by_whom", "")),
            was=str(raw.get("was", "")),
            note=str(raw.get("note", "")),
        )


@dataclass(frozen=True)
class KnowledgeBase:
    """Everything one site has accumulated. Immutable; every change is a new base."""

    site: str
    facts: tuple[Fact, ...] = field(default_factory=tuple)

    def with_facts(self, *facts: Fact) -> KnowledgeBase:
        return replace(self, facts=self.facts + tuple(facts))

    def usable(self) -> tuple[Fact, ...]:
        """The facts reasoning may use — declared and derived only."""
        return tuple(f for f in self.facts if f.usable)

    def pending_review(self) -> tuple[Fact, ...]:
        """Suggestions awaiting a human. Withheld from reasoning, not hidden."""
        return tuple(f for f in self.facts if f.source == SUGGESTED)

    def get(self, key: str) -> Fact:
        """The best-trusted fact for ``key``; raises when trusted sources disagree."""
        candidates = [f for f in self.facts if f.key == key]
        if not candidates:
            raise KeyError(f"No fact for {key!r} at site {self.site!r}.")
        best_rank = min(TRUST_ORDER.index(f.source) for f in candidates)
        top = [f for f in candidates if TRUST_ORDER.index(f.source) == best_rank]
        values = {repr(f.value) for f in top}
        if len(values) > 1:
            raise ValueError(
                f"Conflict on {key!r}: {' vs '.join(sorted(values))}, both "
                f"{TRUST_ORDER[best_rank]}. Two sources of equal standing disagree — "
                "that is for a person to settle, not for this to average away."
            )
        return top[0]

    def conflicts(self) -> tuple[str, ...]:
        """Keys where equally-trusted sources disagree, so they can be found at once."""
        bad = []
        for key in sorted({f.key for f in self.facts}):
            try:
                self.get(key)
            except ValueError:
                bad.append(key)
        return tuple(bad)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": _FORMAT_VERSION,
            "site": self.site,
            "facts": [f.as_dict() for f in self.facts],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> KnowledgeBase:
        """Rebuild from stored JSON. A bad provenance FAILS rather than defaulting.

        Defaulting an unreadable source would silently make every stored
        suggestion usable — precisely the failure this module exists to prevent,
        arriving through the back door of a corrupt file.
        """
        if not isinstance(raw, dict):
            raise ValueError(f"A knowledge base must be an object, got {type(raw).__name__}.")
        return cls(
            site=str(raw.get("site", "")),
            facts=tuple(Fact.from_dict(f) for f in (raw.get("facts") or ())),
        )


__all__ = [
    "DECLARED",
    "DERIVED",
    "SUGGESTED",
    "TRUST_ORDER",
    "USABLE_SOURCES",
    "Fact",
    "KnowledgeBase",
]
