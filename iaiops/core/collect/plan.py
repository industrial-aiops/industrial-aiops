"""A collection plan — what to sample, how fast, and for how long.

The plan is a validated object rather than a pile of CLI arguments because
**a run that lasts a week must be impossible to start by accident**.

This is also how a long run stays inside a rule the connectors already follow.
``opcua.subscribe_sample`` caps at 200 samples / 60 seconds and says "never an
unbounded loop"; that rule protects a plant from a tool that forgets to stop. An
assessment run does not break it — there is still **no run-forever mode**. It
raises the ceiling and forces the operator to state the end explicitly, which is
also what makes the run approvable: a resident process on an OT network needs
change management, a run that says when it ends is a much smaller ask (D21).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: A fortnight. Long enough for the multi-week assessment D21 describes, short
#: enough that a typo cannot start something that outlives the engagement.
MAX_DURATION_S = 14 * 86_400

#: Below this the collector spends more time in overhead than sampling, and a
#: plant network sees a read storm. Matches the connectors' own floor.
MIN_INTERVAL_MS = 50

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdw])$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86_400, "w": 604_800}


def parse_duration(text: str) -> int:
    """``"7d"`` → 604800. A bare number is refused — seven of what?

    Guessing a unit here would be the same class of mistake as guessing a
    semantic role: the result looks plausible and is wrong by a factor of 86400.
    """
    match = _DURATION.match(str(text).strip().lower())
    if not match:
        raise ValueError(
            f"Duration {text!r} needs an explicit unit — one of s/m/h/d/w (e.g. '30m', '7d')."
        )
    seconds = int(float(match.group(1)) * _UNIT_S[match.group(2)])
    if seconds <= 0:
        raise ValueError(f"Duration {text!r} must be positive.")
    return seconds


@dataclass(frozen=True)
class CollectionPlan:
    """One bounded collection run over a named set of tags."""

    endpoint: str
    tags: tuple[str, ...]
    duration_s: int
    interval_ms: int = 1000
    note: str = field(default="")

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("A plan needs an endpoint.")
        if not self.tags:
            raise ValueError(
                "A plan needs at least one tag. Collecting 'everything' is how a "
                "week-long run fills a disk — name the points that matter."
            )
        if self.duration_s <= 0:
            raise ValueError("Duration must be positive.")
        if self.duration_s > MAX_DURATION_S:
            raise ValueError(
                f"Duration {self.duration_s}s exceeds the {MAX_DURATION_S}s cap "
                f"({MAX_DURATION_S // 86_400} days). Refused rather than clamped — a "
                "silently shortened run would leave you believing you had more history."
            )
        if self.interval_ms < MIN_INTERVAL_MS:
            raise ValueError(
                f"Sample interval {self.interval_ms}ms is below the {MIN_INTERVAL_MS}ms floor."
            )

    @property
    def resolves_stops_shorter_than_s(self) -> float:
        """The shortest stoppage this rate can actually witness.

        Two samples are needed to see a state change and change back, so the
        floor is twice the interval. The whole OEE case rests on catching minor
        stoppages, and a plan that cannot state what it resolves cannot be
        checked against that claim.
        """
        return round(2.0 * self.interval_ms / 1000.0, 3)

    @property
    def resolution_note(self) -> str:
        return (
            f"At {self.interval_ms}ms this run cannot see a stoppage shorter than "
            f"{self.resolves_stops_shorter_than_s:g}s — shorter stops stay invisible, "
            "exactly as they are to a manual count."
        )

    @property
    def estimated_rows(self) -> int:
        """Cost before the run, not after."""
        per_tag = int(self.duration_s * 1000 / self.interval_ms)
        return per_tag * len(self.tags)

    @property
    def summary(self) -> str:
        days = self.duration_s / 86_400
        span = f"{days:.1f}d" if days >= 1 else f"{self.duration_s / 3600:.1f}h"
        return (
            f"{len(self.tags)} tag(s) on {self.endpoint} every {self.interval_ms}ms "
            f"for {span} → about {self.estimated_rows:,} rows. {self.resolution_note}"
        )


__all__ = ["CollectionPlan", "parse_duration", "MAX_DURATION_S", "MIN_INTERVAL_MS"]
