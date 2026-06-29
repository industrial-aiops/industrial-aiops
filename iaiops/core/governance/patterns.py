"""L5 auto-remediation pattern engine.

Implements the pattern matcher described in
``docs/auto-remediation-patterns.md``. Patterns are loaded from
``~/.iaiops/auto-remediation-patterns/*.yaml`` (hot-reload on mtime change)
and consulted by the ``@governed_tool`` decorator on every call.

Scope (PoC):
  - Pattern loading and signature validation
  - Action matching (is the current tool+params an armed pattern's action?)
  - Rate limiting (per-pattern, per-target)
  - Circuit breaker (3 consecutive validation failures → 24h disable)
  - In-memory state — survives the MCP server process lifetime, NOT restarts

Out of scope (future work — separate worker / daemon):
  - Trigger matching against historical audit events
  - Automatic action execution
  - Validation post-step
  - Persistent rate-limit / circuit-breaker state across restarts
  - Approval channel for human signing

Failure modes are deliberately fail-open: if pattern loading or matching
errors out, the decorator falls through to normal behavior with a warning.
A broken pattern file must not block all MCP tool calls.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops.core.governance.paths import ops_path

_log = logging.getLogger("iaiops.patterns")

_REQUIRED_TOP_LEVEL_KEYS = ("schema_version", "pattern_id", "classification", "action")
_REQUIRED_CLASSIFICATION_KEYS = ("risk", "reversible", "repeatable")


@dataclass(frozen=True)
class Pattern:
    """A loaded, signature-validated auto-remediation pattern."""

    pattern_id: str
    skill: str             # action.skill
    tool: str              # action.tool
    risk: str              # classification.risk — must be "low" to be armable
    reversible: bool
    repeatable: bool
    expires_at: str        # ISO date or "" if never
    rate_max_per_hour_per_target: int
    rate_max_per_day_per_target: int
    circuit_threshold: int  # consecutive failures → disable
    circuit_disable_seconds: int
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_armable(self) -> bool:
        """The hard preconditions per the design doc."""
        return (
            self.risk == "low"
            and self.reversible is True
            and self.repeatable is True
            and not self.is_expired
        )

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            return datetime.now(tz=UTC) > exp
        except (ValueError, TypeError):
            _log.warning("pattern %s has malformed expires_at=%r — treating as expired",
                         self.pattern_id, self.expires_at)
            return True


@dataclass
class PatternMatch:
    """Result of consulting the pattern engine for a tool call."""

    pattern: Pattern
    armed: bool                # True if rate limit + circuit breaker permit firing
    reason: str = ""           # Human-readable explanation (esp. when not armed)


@dataclass
class _Counters:
    """Per-(pattern_id, target) sliding-window state."""

    arm_timestamps: list[float] = field(default_factory=list)  # epoch seconds
    consecutive_failures: int = 0
    disabled_until: float = 0.0  # epoch seconds


class PatternEngine:
    """Singleton pattern matcher integrated with @governed_tool."""

    def __init__(self, patterns_dir: Path | str | None = None) -> None:
        self._dir = (
            Path(patterns_dir).expanduser() if patterns_dir
            else ops_path("auto-remediation-patterns")
        )
        self._patterns: dict[str, Pattern] = {}
        self._mtimes: dict[Path, float] = {}
        # _counters keyed by (pattern_id, target) — target may be ""
        self._counters: dict[tuple[str, str], _Counters] = {}
        self._lock = threading.Lock()
        self._load()

    # ── Pattern loading ───────────────────────────────────────────────

    def _load(self) -> None:
        """Load all *.yaml files from the patterns directory.

        Bad files are skipped with a warning; good files replace prior state.
        """
        if not self._dir.exists():
            self._patterns = {}
            self._mtimes = {}
            return

        try:
            import yaml
        except ImportError:
            _log.warning("PyYAML not installed — pattern engine disabled")
            self._patterns = {}
            return

        new_patterns: dict[str, Pattern] = {}
        new_mtimes: dict[Path, float] = {}
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                new_mtimes[path] = path.stat().st_mtime
                with open(path) as fh:
                    raw = yaml.safe_load(fh) or {}
                pat = self._validate(raw, path)
                if pat is not None:
                    if pat.pattern_id in new_patterns:
                        _log.warning("duplicate pattern_id %r in %s — keeping first",
                                     pat.pattern_id, path)
                        continue
                    new_patterns[pat.pattern_id] = pat
            except Exception:
                _log.warning("failed to load pattern %s", path, exc_info=True)

        self._patterns = new_patterns
        self._mtimes = new_mtimes

    def _maybe_reload(self) -> None:
        """Reload if any file's mtime changed or new files appeared."""
        if not self._dir.exists():
            if self._patterns:
                _log.warning("patterns dir deleted — clearing %d patterns", len(self._patterns))
                self._patterns = {}
                self._mtimes = {}
            return
        try:
            current_files = set(self._dir.glob("*.yaml"))
            tracked_files = set(self._mtimes.keys())
            if current_files != tracked_files:
                self._load()
                return
            for path in current_files:
                if path.stat().st_mtime != self._mtimes.get(path, 0):
                    self._load()
                    return
        except Exception:
            _log.warning("failed to check patterns dir", exc_info=True)

    @staticmethod
    def _validate(raw: dict[str, Any], path: Path) -> Pattern | None:
        """Validate signature + return a Pattern, or None if invalid."""
        for k in _REQUIRED_TOP_LEVEL_KEYS:
            if k not in raw:
                _log.warning("pattern %s missing required key %r — skipped", path, k)
                return None

        if raw.get("schema_version") != 1:
            _log.warning("pattern %s has schema_version=%r (expected 1) — skipped",
                         path, raw.get("schema_version"))
            return None

        cls_block = raw.get("classification", {})
        for k in _REQUIRED_CLASSIFICATION_KEYS:
            if k not in cls_block:
                _log.warning("pattern %s missing classification.%s — skipped", path, k)
                return None

        action = raw.get("action", {})
        skill = action.get("skill")
        tool = action.get("tool")
        if not skill or not tool:
            _log.warning("pattern %s missing action.skill or action.tool — skipped", path)
            return None

        # Patterns with status != approved are NOT armable. We still load them
        # so callers can introspect, but is_armable returns False.
        approval_status = (raw.get("approval", {}) or {}).get("status", "")
        # Effectively makes risk=high if not approved — but cleaner to keep the
        # explicit approval gate. We honor the YAML's classification.risk and let
        # the approval status influence armability via signed_by check below.
        signed_by = (raw.get("approval", {}) or {}).get("signed_by") or ""

        rate = raw.get("rate_limit", {}) or {}
        cb = raw.get("circuit_breaker", {}) or {}

        # Force unsigned patterns to be non-armable by setting risk to a
        # non-"low" sentinel. Loading still succeeds for inspection.
        effective_risk = cls_block.get("risk", "")
        # Both gates required: signed AND approved. A signed-but-rejected pattern
        # must NOT be armable (yjs review 2026-05-06 — previously the OR-style
        # check let signed-rejected slip through with original risk).
        if not signed_by or approval_status != "approved":
            effective_risk = "unsigned"

        return Pattern(
            pattern_id=str(raw.get("pattern_id")),
            skill=str(skill),
            tool=str(tool),
            risk=str(effective_risk),
            reversible=bool(cls_block.get("reversible", False)),
            repeatable=bool(cls_block.get("repeatable", False)),
            expires_at=str(raw.get("expires_at") or ""),
            rate_max_per_hour_per_target=int(
                rate.get("max_per_hour", rate.get("max_per_hour_per_host", 0)) or 0
            ),
            rate_max_per_day_per_target=int(
                rate.get("max_per_day", rate.get("max_per_day_per_cluster", 0)) or 0
            ),
            circuit_threshold=int(cb.get("consecutive_validation_failures", 3) or 3),
            circuit_disable_seconds=int(cb.get("disable_seconds", 86400) or 86400),
            raw=raw,
        )

    # ── Public matching API ───────────────────────────────────────────

    def match(self, skill: str, tool: str, target: str) -> PatternMatch | None:
        """Return a PatternMatch if any loaded pattern's action matches.

        Returns None if no pattern's action matches this (skill, tool).

        When a pattern matches, the result indicates whether it is currently
        armed — i.e., whether rate limit allows it AND circuit breaker is
        not tripped. The decorator can use armed=True as a hint to skip
        double-confirm; armed=False means the pattern exists but is rate-limited
        or in cooldown.
        """
        self._maybe_reload()

        # Collect every pattern whose action matches, then prefer the first
        # ARMABLE one. Previously the first (skill, tool) match won even when
        # not armable, shadowing a later armable pattern.
        candidates = [
            p for p in self._patterns.values()
            if p.skill == skill and p.tool == tool
        ]
        if not candidates:
            return None

        armable = [p for p in candidates if p.is_armable]
        if not armable:
            pat = candidates[0]
            return PatternMatch(pattern=pat, armed=False,
                                reason=f"pattern {pat.pattern_id} is not armable "
                                       f"(risk={pat.risk}, expired={pat.is_expired})")

        for pat in armable:
            with self._lock:
                key = (pat.pattern_id, target or "")
                ctr = self._counters.setdefault(key, _Counters())

                # Circuit breaker check
                now = time.time()
                if now < ctr.disabled_until:
                    remaining = int(ctr.disabled_until - now)
                    return PatternMatch(
                        pattern=pat, armed=False,
                        reason=f"pattern {pat.pattern_id} circuit-broken for "
                               f"~{remaining}s after {ctr.consecutive_failures} failures",
                    )

                # Rate limit check (sliding 1h and 24h windows)
                hour_ago = now - 3600
                day_ago = now - 86400
                ctr.arm_timestamps = [t for t in ctr.arm_timestamps if t > day_ago]
                arms_last_hour = sum(1 for t in ctr.arm_timestamps if t > hour_ago)
                arms_last_day = len(ctr.arm_timestamps)

                if pat.rate_max_per_hour_per_target and arms_last_hour >= pat.rate_max_per_hour_per_target:
                    return PatternMatch(
                        pattern=pat, armed=False,
                        reason=f"pattern {pat.pattern_id} hit hourly cap "
                               f"({pat.rate_max_per_hour_per_target}/h) on target {target!r}",
                    )
                if pat.rate_max_per_day_per_target and arms_last_day >= pat.rate_max_per_day_per_target:
                    return PatternMatch(
                        pattern=pat, armed=False,
                        reason=f"pattern {pat.pattern_id} hit daily cap "
                               f"({pat.rate_max_per_day_per_target}/d) on target {target!r}",
                    )

                # Pattern is armed — record the arming timestamp
                ctr.arm_timestamps.append(now)

            return PatternMatch(pattern=pat, armed=True,
                                reason=f"pattern {pat.pattern_id} armed")

        return None

    def report_outcome(self, pattern_id: str, target: str, success: bool) -> None:
        """Update circuit-breaker state after an armed pattern's action ran.

        Called by the decorator's finally block once the underlying tool
        function returns or raises. Successful runs reset the failure
        counter; failures increment it and may trip the breaker.
        """
        with self._lock:
            key = (pattern_id, target or "")
            ctr = self._counters.setdefault(key, _Counters())
            pat = self._patterns.get(pattern_id)
            threshold = pat.circuit_threshold if pat else 3
            disable_for = pat.circuit_disable_seconds if pat else 86400

            if success:
                ctr.consecutive_failures = 0
                return

            ctr.consecutive_failures += 1
            if ctr.consecutive_failures >= threshold:
                ctr.disabled_until = time.time() + disable_for
                _log.warning(
                    "pattern %s circuit-broken on target %r after %d failures — "
                    "disabled for %ds",
                    pattern_id, target, ctr.consecutive_failures, disable_for,
                )

    # ── Introspection / testing helpers ──────────────────────────────

    def loaded_patterns(self) -> list[Pattern]:
        """Return a snapshot of currently loaded patterns."""
        return list(self._patterns.values())

    def reset_state(self) -> None:
        """Clear in-memory counters. Used by tests; not for production paths."""
        with self._lock:
            self._counters = {}


# ── Singleton ─────────────────────────────────────────────────────────

_engine: PatternEngine | None = None
_engine_lock = threading.Lock()


def get_pattern_engine(patterns_dir: Path | str | None = None) -> PatternEngine:
    """Return the global PatternEngine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PatternEngine(patterns_dir)
    return _engine


def reset_pattern_engine() -> None:
    """Reset the singleton. Tests use this to swap directories cleanly."""
    global _engine
    _engine = None
