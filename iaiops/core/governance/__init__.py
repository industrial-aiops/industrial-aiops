"""Governance harness for iaiops — audit, policy, budget, undo, sanitize.

A self-contained, vendored governance layer. iaiops has NO dependency on
any external skill family — this package is its own copy of the harness:

  - ``@governed_tool`` — mandatory decorator on every MCP tool: policy pre-check,
    token/runaway budget guard, graduated-autonomy risk-tier gate, audit logging,
    and undo-token recording.
  - unified SQLite audit log under ``~/.iaiops/`` (override with
    ``IAIOPS_HOME``).
  - ``sanitize`` — prompt-injection defense for API-returned text.

State lives under ``ops_home()`` (default ``~/.iaiops``).
"""

from iaiops.core.governance.audit import AuditEngine, get_engine
from iaiops.core.governance.budget import BudgetExceeded, BudgetTracker, get_budget
from iaiops.core.governance.decorators import PolicyDenied, governed_tool
from iaiops.core.governance.patterns import Pattern, PatternMatch, get_pattern_engine
from iaiops.core.governance.policy import TierDecision, get_policy_engine
from iaiops.core.governance.sanitize import sanitize
from iaiops.core.governance.undo import UndoStore, get_undo_store

__all__ = [
    "governed_tool",
    "sanitize",
    "PolicyDenied",
    "get_engine",
    "AuditEngine",
    "get_policy_engine",
    "TierDecision",
    "get_budget",
    "BudgetTracker",
    "BudgetExceeded",
    "get_undo_store",
    "UndoStore",
    "Pattern",
    "PatternMatch",
    "get_pattern_engine",
]
