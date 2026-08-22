"""Readiness — what this installation can actually do today."""

from __future__ import annotations

from iaiops.core.readiness.assess import assess, gather_facts
from iaiops.core.readiness.model import (
    BLOCKED,
    DEGRADED,
    READY,
    Capability,
    ReadinessReport,
    Requirement,
)

__all__ = [
    "assess",
    "gather_facts",
    "READY",
    "DEGRADED",
    "BLOCKED",
    "Requirement",
    "Capability",
    "ReadinessReport",
]
