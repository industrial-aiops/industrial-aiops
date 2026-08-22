"""Continuous collection — bounded runs that fill the local store."""

from __future__ import annotations

from iaiops.core.collect.plan import (
    MAX_DURATION_S,
    MIN_INTERVAL_MS,
    CollectionPlan,
    parse_duration,
)

__all__ = ["CollectionPlan", "parse_duration", "MAX_DURATION_S", "MIN_INTERVAL_MS"]
