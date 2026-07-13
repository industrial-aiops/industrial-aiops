"""Policy engine — rule-based access control for network MCP tools.

Rules are loaded from ``~/.iaiops/rules.yaml`` with hot-reload on file change.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from iaiops.core.governance.paths import ops_path

_log = logging.getLogger("iaiops.policy")

# ── Data structures ───────────────────────────────────────────────────


@dataclass(frozen=True)
class PolicyResult:
    """Outcome of a policy check."""

    allowed: bool
    rule: str = ""
    reason: str = ""


@dataclass(frozen=True)
class TierDecision:
    """Graduated-autonomy outcome: the approval tier an operation needs.

    tier is one of APPROVAL_TIERS. ``requires_approver`` is True for tiers that
    must carry a named human approver (dual / review) — the decorator denies
    such calls when no approver is recorded.
    """

    tier: str = "none"
    rule: str = "default"
    reason: str = ""

    @property
    def requires_approver(self) -> bool:
        return self.tier in ("dual", "review")


# ── Risk levels ───────────────────────────────────────────────────────

RISK_LEVELS = ("low", "medium", "high", "critical")

# Graduated autonomy tiers, least → most oversight.
#   none    — no gate (dev / low-risk)
#   confirm — CLI double-confirm (informational at the harness layer)
#   dual    — requires a named approver to be recorded (two-person rule)
#   review  — requires a named approver + intended for explicit human review
APPROVAL_TIERS = ("none", "confirm", "dual", "review")

# Param keys whose string values are treated as resource tags / placement for
# tier matching (e.g. a VM's folder or environment tag: prod/staging/dev).
_TAG_PARAM_KEYS = ("tag", "tags", "folder", "resource_tag", "env_tier", "environment")


# ── Kill-switch env handling ──────────────────────────────────────────

# Risk levels the policy kill switch must NEVER bypass: deny rules and
# approver tiers stay enforced for these even when policy is "disabled".
_BYPASS_EXEMPT_RISK = ("high", "critical")

_POLICY_DISABLED_ENV = "IAIOPS_POLICY_DISABLED"
_LEGACY_POLICY_DISABLED_ENV = "OPCUA_POLICY_DISABLED"

_legacy_disable_warned = False


def _policy_disabled() -> bool:
    """True when the policy kill switch env var is set.

    Accepts the new ``IAIOPS_POLICY_DISABLED`` name; the legacy
    ``OPCUA_POLICY_DISABLED`` still works but logs a deprecation warning once
    per process.
    """
    global _legacy_disable_warned
    if os.environ.get(_POLICY_DISABLED_ENV) == "1":
        return True
    if os.environ.get(_LEGACY_POLICY_DISABLED_ENV) == "1":
        if not _legacy_disable_warned:
            _legacy_disable_warned = True
            _log.warning(
                "%s is deprecated — use %s instead.",
                _LEGACY_POLICY_DISABLED_ENV, _POLICY_DISABLED_ENV,
            )
        return True
    return False


# ── Rule loading with hot-reload ──────────────────────────────────────


class PolicyEngine:
    """Evaluate operations against a YAML rule set.

    Rules file is re-read when its mtime changes (hot-reload, no restart needed).
    """

    def __init__(self, rules_path: Path | str | None = None) -> None:
        self._path = Path(rules_path).expanduser() if rules_path else ops_path("rules.yaml")
        self._rules: dict[str, Any] = {}
        self._mtime: float = 0.0
        self._deletion_warned = False
        self._load_rules()

    def _load_rules(self) -> None:
        """Load rules from YAML file.  Missing file → empty rules.

        Fail CLOSED on a bad rules file: a parse failure RETAINS the previous
        (last-known-good) rule set for the process lifetime instead of
        degrading to allow-all, and the failure is recorded on the audit trail
        (status ``policy_load_failed``) so operators notice.
        """
        if not self._path.exists():
            self._rules = {}
            self._mtime = 0.0
            return
        try:
            import yaml

            self._mtime = self._path.stat().st_mtime
            with open(self._path) as fh:
                loaded = yaml.safe_load(fh)
            if loaded is not None and not isinstance(loaded, dict):
                raise ValueError(f"rules.yaml must be a mapping, got {type(loaded).__name__}")
            candidate = loaded or {}
            # Fail CLOSED on unenforceable change_limits: a bad shape raises
            # here so the standard load-failure path applies (last-known-good
            # rules retained + audited) instead of a runtime "not enforced"
            # warning that silently drops the limit.
            _validate_change_limits(candidate.get("change_limits"))
            self._rules = candidate
            self._deletion_warned = False
            _log.debug("Loaded %d policy rules from %s", len(self._rules), self._path)
        except Exception as exc:
            _log.error(
                "Failed to load policy rules from %s — RETAINING previous rule "
                "set (fail closed, not allow-all). Fix the file to re-enable "
                "hot-reload of new rules.",
                self._path, exc_info=True,
            )
            self._audit_load_failure(f"{type(exc).__name__}: {exc}")

    def _audit_load_failure(self, error: str) -> None:
        """Record a policy-load failure on the audit trail (best-effort)."""
        try:
            from iaiops.core.governance.audit import get_engine

            get_engine().log(
                skill="iaiops",
                tool="policy_engine",
                params={"rules_path": str(self._path)},
                result={"error": error},
                status="policy_load_failed",
                risk_level="high",
            )
        except Exception:  # noqa: BLE001 — audit of the failure is best-effort
            _log.warning("Could not audit policy load failure", exc_info=True)

    def _maybe_reload(self) -> None:
        """Hot-reload if file changed.

        Deleting the rules file does NOT clear the in-memory rules: the
        last-known-good rule set stays enforced (fail closed) until the file
        reappears with valid content.
        """
        if not self._path.exists():
            if self._rules and not self._deletion_warned:
                self._deletion_warned = True
                _log.error(
                    "Policy rules file deleted: %s — KEEPING last-known-good "
                    "rules in memory (fail closed). Restore the file to change "
                    "policy.",
                    self._path,
                )
                self._audit_load_failure("rules file deleted — last-known-good rules retained")
            self._mtime = 0.0
            return
        try:
            current_mtime = self._path.stat().st_mtime
            if current_mtime != self._mtime:
                self._load_rules()
        except Exception:
            _log.warning("Failed to check policy rules file: %s", self._path, exc_info=True)

    def check_allowed(
        self,
        operation: str,
        *,
        env: str = "",
        risk_level: str = "low",
        params: dict[str, Any] | None = None,
    ) -> PolicyResult:
        """Check if an operation is allowed by policy.

        Args:
            operation: Tool function name (e.g. 'delete_segment').
            env: Target environment name (e.g. 'production').
            risk_level: Risk level declared by @governed_tool.
            params: Operation parameters for rule evaluation.

        Returns:
            PolicyResult with allowed=True/False and reason.
        """
        # Bypass mode — log context for audit trail. Log only parameter NAMES,
        # never values: param values may carry passwords/tokens, and this path
        # can be reached by callers that did not pre-redact.
        # The kill switch is scoped: it NEVER bypasses high/critical-risk
        # operations — deny rules, maintenance windows, and approver tiers
        # stay enforced for those.
        if _policy_disabled():
            if risk_level in _BYPASS_EXEMPT_RISK:
                _log.warning(
                    "Policy disable requested but IGNORED for %s-risk operation "
                    "%s — high/critical operations are never bypassed.",
                    risk_level, operation,
                )
            else:
                param_names = sorted(params.keys()) if isinstance(params, dict) else []
                _log.warning(
                    "Policy DISABLED — bypassing check: operation=%s env=%s risk=%s param_keys=%s",
                    operation, env, risk_level, param_names,
                )
                return PolicyResult(allowed=True, rule="policy_disabled")

        self._maybe_reload()

        # No rules file → allow everything
        if not self._rules:
            return PolicyResult(allowed=True, rule="no_rules")

        # ── Evaluate deny rules ───────────────────────────────────────
        deny_rules = self._rules.get("deny", [])
        for rule in deny_rules:
            if self._rule_matches(rule, operation, env, risk_level, params):
                reason = rule.get("reason", f"Denied by rule: {rule.get('name', 'unnamed')}")
                return PolicyResult(allowed=False, rule=rule.get("name", "deny"), reason=reason)

        # ── Evaluate maintenance window ───────────────────────────────
        window = self._rules.get("maintenance_window")
        if window and risk_level in ("high", "critical"):
            try:
                in_window = self._in_maintenance_window(window)
            except (ValueError, TypeError, AttributeError):
                # Fail CLOSED: a malformed window must not silently allow
                # high-risk operations around the clock.
                _log.error(
                    "Malformed maintenance_window %r in %s — failing CLOSED: "
                    "high-risk operations are blocked until the rule is fixed. "
                    "Expected 'start' and 'end' as 'HH:MM' strings, e.g. "
                    "start: \"22:00\" / end: \"06:00\".",
                    window, self._path,
                )
                return PolicyResult(
                    allowed=False,
                    rule="maintenance_window_malformed",
                    reason=(
                        f"maintenance_window in {self._path} is malformed "
                        f"({window!r}). High-risk operations are blocked until it is "
                        "fixed. Expected 'start' and 'end' as 'HH:MM' strings, "
                        'e.g. start: "22:00" / end: "06:00".'
                    ),
                )
            if not in_window:
                return PolicyResult(
                    allowed=False,
                    rule="maintenance_window",
                    reason=f"High-risk operations only allowed during {window.get('start', '?')}-{window.get('end', '?')}",
                )

        # ── Evaluate change limits ────────────────────────────────────
        limits = self._rules.get("change_limits")
        if limits:
            result = self._check_limits(limits, params or {}, operation)
            if result is not None:
                return result

        return PolicyResult(allowed=True, rule="default_allow")

    def required_approval_tier(
        self,
        operation: str,
        *,
        env: str = "",
        risk_level: str = "low",
        params: dict[str, Any] | None = None,
    ) -> TierDecision:
        """Return the approval tier this operation needs (graduated autonomy).

        Evaluated from a ``risk_tiers`` list in rules.yaml — each entry matches
        on operation glob / environment / resource tag / minimum risk and maps
        to a tier (none/confirm/dual/review). The FIRST matching, HIGHEST tier
        wins so a prod-tagged destructive op can't be down-graded by a looser
        rule listed earlier.

        No ``risk_tiers`` config → a hardcoded SAFE default applies: high /
        critical risk operations require a named approver (tier ``dual``,
        rule ``builtin_default``). Low/medium stay tier ``none``. Operators
        tune this by declaring explicit ``risk_tiers`` (``iaiops init`` writes
        a starter rules.yaml).
        """
        self._maybe_reload()
        tiers = self._rules.get("risk_tiers") if self._rules else None
        if not tiers:
            if risk_level in _BYPASS_EXEMPT_RISK:
                return TierDecision(
                    tier="dual",
                    rule="builtin_default",
                    reason=(
                        "No risk_tiers configured — builtin safe default: "
                        "high/critical-risk operations require a named approver. "
                        "Declare risk_tiers in rules.yaml to tune this."
                    ),
                )
            return TierDecision(tier="none", rule="no_tiers")

        tags = _extract_tags(params)
        best: TierDecision | None = None
        for rule in tiers:
            tier = str(rule.get("tier", "")).lower()
            if tier not in APPROVAL_TIERS:
                continue
            if not self._tier_rule_matches(rule, operation, env, risk_level, tags):
                continue
            if best is None or APPROVAL_TIERS.index(tier) > APPROVAL_TIERS.index(best.tier):
                best = TierDecision(
                    tier=tier,
                    rule=str(rule.get("name", "risk_tier")),
                    reason=str(rule.get("reason", "")),
                )
        return best or TierDecision(tier="none", rule="no_tier_match")

    def _tier_rule_matches(
        self,
        rule: dict[str, Any],
        operation: str,
        env: str,
        risk_level: str,
        tags: set[str],
    ) -> bool:
        """Match a risk_tiers entry against the current call."""
        if "operations" in rule:
            ops = rule["operations"]
            if not ops or not any(self._pattern_match(op, operation) for op in ops):
                return False
        envs = rule.get("environments", [])
        if envs and env and env not in envs:
            return False
        if envs and not env:
            return False  # rule scoped to envs but call has none → no match
        rule_tags = {str(t) for t in (rule.get("tags") or [])}
        if rule_tags and not (rule_tags & tags):
            return False
        min_risk = rule.get("min_risk_level")
        if min_risk and RISK_LEVELS.index(risk_level) < RISK_LEVELS.index(min_risk):
            return False
        return True

    def _rule_matches(
        self,
        rule: dict[str, Any],
        operation: str,
        env: str,
        risk_level: str,
        params: dict[str, Any] | None,
    ) -> bool:
        """Check if a deny rule matches the current operation."""
        # Match by operation pattern
        # Note: "operations" key absent → match all (no filter).
        # "operations: []" → match nothing (explicit empty = no operations apply).
        if "operations" in rule:
            ops = rule["operations"]
            if not ops or not any(self._pattern_match(op, operation) for op in ops):
                return False

        # Match by environment
        envs = rule.get("environments", [])
        if envs and env and env not in envs:
            return False

        # Match by risk level (minimum)
        min_risk = rule.get("min_risk_level")
        if min_risk:
            if RISK_LEVELS.index(risk_level) < RISK_LEVELS.index(min_risk):
                return False

        return True

    @staticmethod
    def _pattern_match(pattern: str, value: str) -> bool:
        """Simple glob: 'delete_*' matches 'delete_segment'."""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return value.startswith(pattern[:-1])
        return pattern == value

    @staticmethod
    def _in_maintenance_window(window: dict[str, str]) -> bool:
        """Check if current time is within the maintenance window (UTC).

        Raises ValueError/TypeError/AttributeError when the window is
        malformed — the caller fails CLOSED with a teaching message.
        """
        from datetime import datetime

        now = datetime.now(tz=UTC)
        start_h, start_m = map(int, str(window.get("start", "22:00")).split(":"))
        end_h, end_m = map(int, str(window.get("end", "06:00")).split(":"))

        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes <= end_minutes
        # Wraps midnight (e.g. 22:00 - 06:00)
        return current_minutes >= start_minutes or current_minutes <= end_minutes

    def _check_limits(
        self, limits: Any, params: dict[str, Any], operation: str
    ) -> PolicyResult | None:
        """Enforce numeric ``change_limits`` rules (schema in
        :func:`_validate_change_limits`).

        Returns a denial when a matching rule's bounded param is out of range
        — or cannot be verified as numeric (fail closed) — and ``None`` when
        no rule constrains this call. Malformed rules (reachable only if load
        validation was bypassed) also deny: never warn-and-allow.
        """
        if not isinstance(limits, list):
            return PolicyResult(
                allowed=False,
                rule="change_limits_malformed",
                reason=(
                    f"change_limits in {self._path} is malformed (expected a list "
                    "of limit rules) — denying until the config is fixed."
                ),
            )
        for rule in limits:
            error = _change_limit_rule_error(rule)
            if error:
                return PolicyResult(
                    allowed=False,
                    rule="change_limits_malformed",
                    reason=(
                        f"change_limits rule {rule!r} in {self._path} cannot be "
                        f"enforced ({error}) — denying until the config is fixed."
                    ),
                )
            denial = self._apply_change_limit(rule, params, operation)
            if denial is not None:
                return denial
        return None

    def _apply_change_limit(
        self, rule: dict[str, Any], params: dict[str, Any], operation: str
    ) -> PolicyResult | None:
        """Evaluate one change_limits rule: a denial, or None (not constrained)."""
        ops = rule.get("operations")
        if ops is not None and not any(self._pattern_match(str(op), operation) for op in ops):
            return None
        param = str(rule.get("param"))
        if param not in params:
            return None  # rule matches the op but this call doesn't carry the param
        name = str(rule.get("name", "change_limit"))
        value = _as_number(params[param])
        if value is None:
            return PolicyResult(
                allowed=False,
                rule=name,
                reason=(
                    f"Change limit '{name}' on '{operation}' requires param "
                    f"'{param}' to be numeric to verify it, got "
                    f"{params[param]!r} — denied (fail closed)."
                ),
            )
        minimum, maximum = rule.get("min"), rule.get("max")
        if (minimum is not None and value < float(minimum)) or (
            maximum is not None and value > float(maximum)
        ):
            return _limit_denial(rule, name, operation, param, value)
        return None


def _validate_change_limits(limits: Any) -> None:
    """Validate the ``change_limits`` section at load time (fail closed).

    Schema — a list of numeric limit rules::

        change_limits:
          - name: setpoint_cap          # optional label (used in denials)
            operations: ["write_*"]     # optional glob list; absent → all ops
            param: value                # required: param holding the number
            min: 0                      # at least one numeric bound required
            max: 100
            reason: "..."               # optional operator-facing note

    Raises ValueError on any unenforceable rule so the standard load-failure
    path applies (last-known-good rules retained + audited) instead of a
    runtime warning that silently skips enforcement.
    """
    if limits is None:
        return
    if not isinstance(limits, list):
        raise ValueError(
            "change_limits must be a list of limit rules, got "
            f"{type(limits).__name__} — each rule needs 'param' plus a numeric "
            "'min' and/or 'max'"
        )
    for index, rule in enumerate(limits):
        error = _change_limit_rule_error(rule)
        if error:
            raise ValueError(f"change_limits[{index}] cannot be enforced: {error}")


def _change_limit_rule_error(rule: Any) -> str:
    """Return why a change_limits rule is unenforceable, or '' when valid."""
    if not isinstance(rule, dict):
        return f"expected a mapping, got {type(rule).__name__}"
    param = rule.get("param")
    if not isinstance(param, str) or not param.strip():
        return "'param' (the parameter holding the numeric value) is required"
    bounds = [rule[key] for key in ("min", "max") if rule.get(key) is not None]
    if not bounds:
        return "at least one numeric bound ('min' or 'max') is required"
    for bound in bounds:
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            return f"bounds must be numeric, got {bound!r}"
    ops = rule.get("operations")
    if ops is not None and not isinstance(ops, list):
        return "'operations' must be a list of glob patterns"
    return ""


def _as_number(value: Any) -> float | None:
    """Coerce a param value to float for limit checks; None when not numeric.

    Booleans are rejected (True/False are not setpoint magnitudes) and so is
    NaN (it compares false against every bound and would bypass them); numeric
    strings like "42.5" are accepted since transports often deliver text.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return None if math.isnan(number) else number


def _limit_denial(
    rule: dict[str, Any], name: str, operation: str, param: str, value: float
) -> PolicyResult:
    """Build the operator-facing denial for an out-of-range change limit."""
    bounds = ", ".join(
        f"{key}={rule[key]}" for key in ("min", "max") if rule.get(key) is not None
    )
    reason = (
        f"Denied by change limit '{name}': {operation} {param}={value!r} is "
        f"outside the allowed range ({bounds})."
    )
    note = str(rule.get("reason", "")).strip()
    if note:
        reason += f" {note}"
    return PolicyResult(allowed=False, rule=name, reason=reason)


def _extract_tags(params: dict[str, Any] | None) -> set[str]:
    """Collect resource-tag-like string values from params for tier matching.

    Looks at a fixed set of keys (tag/tags/folder/...) and flattens list values
    so ``{"tags": ["prod", "pci"]}`` and ``{"folder": "prod"}`` both yield
    ``{"prod", ...}``.
    """
    if not params:
        return set()
    out: set[str] = set()
    for key in _TAG_PARAM_KEYS:
        if key not in params:
            continue
        val = params[key]
        if isinstance(val, str):
            out.add(val)
        elif isinstance(val, (list, tuple, set)):
            out.update(str(v) for v in val)
    return out


# ── Singleton ─────────────────────────────────────────────────────────

_engine: PolicyEngine | None = None
_engine_lock = threading.Lock()


def get_policy_engine(rules_path: Path | str | None = None) -> PolicyEngine:
    """Return the global PolicyEngine singleton (lazy, lock-guarded).

    A ``rules_path`` differing from the one the singleton was created with is
    ignored with a warning — call :func:`reset_policy_engine` first to rebind.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PolicyEngine(rules_path)
                return _engine
    if rules_path is not None:
        requested = Path(rules_path).expanduser()
        if requested != _engine._path:
            _log.warning(
                "get_policy_engine(%s) ignored — singleton already initialized "
                "with %s; call reset_policy_engine() first to rebind.",
                requested, _engine._path,
            )
    return _engine


def reset_policy_engine() -> None:
    """Reset the singleton. Mirrors patterns.reset_pattern_engine()."""
    global _engine
    with _engine_lock:
        _engine = None
