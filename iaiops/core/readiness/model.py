"""What a readiness answer is made of.

Three states, and the middle one carries most of the value:

* ``ready`` — every prerequisite is met.
* ``degraded`` — it RUNS, with less than its full evidence. Root-cause analysis
  without a historian still ranks causes; it just cannot see the two hours
  before the stoppage. Collapsing this into "blocked" would tell a site that
  has something useful today that it has nothing.
* ``blocked`` — a required input is absent and the capability cannot run.

The other load-bearing distinction is :attr:`Requirement.expressible`. A
prerequisite can be unmet for two very different reasons: nobody has supplied it
yet, or **there is currently no way to supply it**. Reporting the second as the
first sends someone to search the documentation for a setting that does not
exist. The OEE role mapping is exactly that case today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

READY = "ready"
DEGRADED = "degraded"
BLOCKED = "blocked"

#: Worst-first, so a report can be sorted by "what needs attention".
STATUS_ORDER = (BLOCKED, DEGRADED, READY)


@dataclass(frozen=True)
class Requirement:
    """One prerequisite, and — when unmet — the next action that would meet it."""

    key: str
    label: str
    met: bool
    #: What was actually found. Never a guess; when nothing was found, say so.
    detail: str = ""
    #: The concrete next step. Empty when met.
    fix: str = ""
    #: Unmet OPTIONAL requirements degrade a capability instead of blocking it.
    optional: bool = False
    #: False when the product offers no way to supply this yet — an honesty flag,
    #: because "you have not configured it" and "you cannot configure it" send a
    #: person to two very different places.
    expressible: bool = True

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "met": self.met,
            "detail": self.detail,
        }
        if not self.met:
            out["fix"] = self.fix
            out["optional"] = self.optional
            if not self.expressible:
                out["not_yet_expressible"] = True
        return out


@dataclass(frozen=True)
class Capability:
    """One thing the product can do, and whether this site can do it today."""

    key: str
    label: str
    #: What it gives you — so a blocked row still explains what is being missed.
    value: str
    requirements: tuple[Requirement, ...] = ()

    @property
    def missing_required(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if not r.met and not r.optional)

    @property
    def missing_optional(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if not r.met and r.optional)

    @property
    def status(self) -> str:
        if self.missing_required:
            return BLOCKED
        return DEGRADED if self.missing_optional else READY

    @property
    def headline(self) -> str:
        """One line an operator can act on."""
        if self.status == READY:
            return "ready"
        gaps = self.missing_required or self.missing_optional
        names = ", ".join(r.label for r in gaps)
        prefix = "blocked — needs" if self.status == BLOCKED else "runs, but without"
        return f"{prefix}: {names}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "headline": self.headline,
            "value": self.value,
            "requirements": [r.as_dict() for r in self.requirements],
        }


@dataclass(frozen=True)
class ReadinessReport:
    """The whole picture, plus the facts it was derived from.

    ``facts`` rides along on purpose: every judgement below is reproducible from
    it, so a disputed row can be checked rather than argued about.
    """

    capabilities: tuple[Capability, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def by_status(self, status: str) -> tuple[Capability, ...]:
        return tuple(c for c in self.capabilities if c.status == status)

    @property
    def summary(self) -> dict[str, int]:
        return {s: len(self.by_status(s)) for s in STATUS_ORDER}

    @property
    def blocked_on(self) -> tuple[str, ...]:
        """Distinct prerequisites blocking the most capabilities, worst first.

        The actionable view: a site usually unlocks several scenarios by
        supplying one missing thing, and this names that thing.
        """
        counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        for cap in self.capabilities:
            for req in cap.missing_required:
                counts[req.key] = counts.get(req.key, 0) + 1
                labels[req.key] = req.label
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return tuple(f"{labels[k]} (unlocks {n})" for k, n in ranked)

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "blocked_on": list(self.blocked_on),
            "capabilities": [c.as_dict() for c in self.capabilities],
            "facts": self.facts,
            "notes": list(self.notes),
        }


__all__ = [
    "READY",
    "DEGRADED",
    "BLOCKED",
    "STATUS_ORDER",
    "Requirement",
    "Capability",
    "ReadinessReport",
]
