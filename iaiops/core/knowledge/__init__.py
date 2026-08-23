"""The site knowledge base — what a plant accumulates, with its provenance."""

from __future__ import annotations

from iaiops.core.knowledge.cases import (
    CONFIRMED,
    INFERRED,
    OVERRIDE,
    STATED,
    Case,
    agreement_report,
    case_from_audit,
    to_corpus,
)
from iaiops.core.knowledge.model import (
    DECLARED,
    DERIVED,
    SUGGESTED,
    TRUST_ORDER,
    Fact,
    KnowledgeBase,
)
from iaiops.core.knowledge.store import load, save, site_path

__all__ = [
    # facts and provenance
    "Fact",
    "KnowledgeBase",
    "DECLARED",
    "DERIVED",
    "SUGGESTED",
    "TRUST_ORDER",
    # persistence
    "load",
    "save",
    "site_path",
    # cases — the loop that lets the weights learn from use
    "Case",
    "case_from_audit",
    "to_corpus",
    "agreement_report",
    "STATED",
    "OVERRIDE",
    "CONFIRMED",
    "INFERRED",
]
