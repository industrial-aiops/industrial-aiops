"""The shape of an investigation's readiness — one step, and the walk over eight.

HLD §13. `readiness` answers "which SCENARIOS can this site run"; this answers
"how far into an INVESTIGATION could it get". Both reason over the same
:class:`~iaiops.core.readiness.model.Requirement`, deliberately: the field that
matters most — ``expressible``, "the product offers no way to supply this yet" —
already exists there and already carries the right meaning.

[PURE] No I/O. The assessment that fills these lives in ``assess.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iaiops.core.readiness.model import BLOCKED, DEGRADED, READY, Requirement

__all__ = ["Step", "InvestigationReadiness", "BLOCKED", "DEGRADED", "READY"]


@dataclass(frozen=True)
class Step:
    """One of the eight investigation steps, and whether this site could walk it.

    Structurally a :class:`~iaiops.core.readiness.model.Capability` with an
    order. Kept as its own type rather than reusing that one because the
    ordering is not decoration — ``reachable_through`` is a walk, and a walk
    needs to know which step comes next.
    """

    number: int
    key: str
    label: str
    #: What this step gives you. A blocked row still has to say what is being
    #: missed, or the report is a list of complaints rather than a gap analysis.
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
        if self.status == READY:
            return "ready"
        gaps = self.missing_required or self.missing_optional
        names = ", ".join(r.label for r in gaps)
        # "cannot be supplied" and "has not been supplied" send a person to two
        # different places, so the headline distinguishes them (D36).
        if any(not r.expressible for r in gaps):
            return f"not yet possible — {names}"
        prefix = "blocked — needs" if self.status == BLOCKED else "runs, but without"
        return f"{prefix}: {names}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "headline": self.headline,
            "value": self.value,
            "requirements": [r.as_dict() for r in self.requirements],
        }


@dataclass(frozen=True)
class InvestigationReadiness:
    """Eight steps, and the honest answer to "how far could we get"."""

    site: str
    steps: tuple[Step, ...]

    @property
    def reachable_through(self) -> int:
        """The last step reachable by WALKING from the first.

        Not "how many steps are unblocked": step 5 being satisfiable does not
        help anybody who cannot get past step 2. Zero means the walk stops
        before it starts.
        """
        for step in self.steps:
            if step.status == BLOCKED:
                return step.number - 1
        return self.steps[-1].number if self.steps else 0

    @property
    def blocked_later(self) -> tuple[Step, ...]:
        """Blocked steps BEYOND the walk — reported separately on purpose.

        The knowledge check is missing product-wide today. Letting it collapse
        the headline to "cannot investigate" would understate every site.
        """
        return tuple(
            s for s in self.steps if s.status == BLOCKED and s.number > self.reachable_through + 1
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "steps": [s.as_dict() for s in self.steps],
            "reachable_through": self.reachable_through,
            "total_steps": len(self.steps),
            "blocked_later": [s.key for s in self.blocked_later],
        }
