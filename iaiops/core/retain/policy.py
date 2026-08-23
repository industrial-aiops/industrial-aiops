"""How long raw samples live. Derived facts do not expire.

The measurement behind the split (2026-08-23, this codebase): three tags at 200ms
is **2.0 GB a week** and 102 GB a year, while the stop events derived from that
same year come to about **3 MB**. A factor of thirty-five thousand.

So "what happened in March" stays answerable forever without keeping March's raw
samples — which is what makes continuous collection viable on an edge box rather
than a storage problem someone discovers three months in.

A policy that keeps nothing is refused. "Retain zero days" is not a retention
setting, it is a data-loss switch with a friendly name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Long enough to cover a fortnight's assessment plus the weekend nobody looked
#: at it. At three tags / 1s this is roughly 800 MB.
DEFAULT_RAW_DAYS = 30

#: Below this, an ordinary long weekend would erase the incident someone came
#: back to investigate.
MIN_RAW_DAYS = 3


@dataclass(frozen=True)
class RetentionPolicy:
    """What to keep, and for how long."""

    raw_days: int = DEFAULT_RAW_DAYS
    #: Always ``None``. Derived facts are three orders of magnitude smaller than
    #: the samples behind them, and they are the only thing that can answer a
    #: question about a period whose raw data is gone. Kept as an explicit field
    #: so the intent is visible rather than merely absent.
    derived_days: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.raw_days, int) or isinstance(self.raw_days, bool):
            raise ValueError(f"raw_days must be a whole number of days, got {self.raw_days!r}.")
        if self.raw_days < MIN_RAW_DAYS:
            raise ValueError(
                f"raw_days={self.raw_days} is below the {MIN_RAW_DAYS}-day floor. "
                "Keeping less than that means an ordinary long weekend erases the "
                "incident someone came back to investigate."
            )
        if self.derived_days is not None:
            raise ValueError(
                "derived_days must stay unset — derived facts are ~35,000x smaller "
                "than the samples behind them and are the only way to answer about a "
                "period whose raw data has expired."
            )

    @property
    def summary(self) -> str:
        return (
            f"Raw samples are kept for {self.raw_days} days; derived facts "
            "(stoppages, per-shift figures, baselines) never expire — they are small "
            "enough that expiring them would save nothing and cost the whole history."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_days": self.raw_days,
            "derived_days": None,
            "summary": self.summary,
        }


__all__ = ["RetentionPolicy", "DEFAULT_RAW_DAYS", "MIN_RAW_DAYS"]
