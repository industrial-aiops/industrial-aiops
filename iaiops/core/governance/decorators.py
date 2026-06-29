"""The ``@governed_tool`` decorator — mandatory wrapper for all network MCP tool functions.

Responsibilities:
  1. Pre-check: evaluate policy rules (deny, maintenance window)
  2. Execute: run the actual tool function
  3. Post-log: write audit record to ``~/.iaiops/audit.db``
  4. Metadata: attach risk_level, idempotent, timeout, sensitive_params

Usage::

    from iaiops.core.governance import governed_tool

    @governed_tool(risk_level="high", sensitive_params=["password"])
    def delete_segment(name: str, env: str) -> dict:
        ...

Registration enforcement::

    # In your MCP server startup
    for tool in tools:
        assert getattr(tool, "_is_governed_tool", False), f"{tool.__name__} missing @governed_tool"
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import time
import traceback
from functools import wraps
from typing import Any

from iaiops.core.governance.audit import detect_agent, get_engine
from iaiops.core.governance.budget import BudgetExceeded, get_budget
from iaiops.core.governance.patterns import PatternMatch, get_pattern_engine
from iaiops.core.governance.policy import PolicyResult, get_policy_engine
from iaiops.core.governance.sanitize import sanitize

_log = logging.getLogger("iaiops.decorators")


class PolicyDenied(Exception):
    """Raised when an operation is denied by policy."""

    def __init__(self, result: PolicyResult) -> None:
        self.result = result
        super().__init__(result.reason)


def governed_tool(
    fn: Any = None,
    *,
    risk_level: str = "low",
    idempotent: bool = False,
    timeout_seconds: int = 300,
    sensitive_params: list[str] | None = None,
    undo: Any = None,
) -> Any:
    """Decorator for all network MCP tool functions.

    Can be used with or without arguments::

        @governed_tool
        def list_segments(...): ...

        @governed_tool(risk_level="critical", sensitive_params=["password"])
        def delete_vm(...): ...

    Args:
        risk_level: One of 'low', 'medium', 'high', 'critical'.
        idempotent: Whether the operation can be safely retried on failure.
        timeout_seconds: Maximum execution time before warning — exceeding it
            logs a warning (no hard cancellation).
        sensitive_params: Parameter names to redact in audit logs.
        undo: Optional callable ``(params, result) -> dict | None`` returning an
            inverse descriptor ``{"tool", "params", "skill"?, "note"?}``. On a
            successful call the inverse is recorded to ~/.iaiops/undo.db and the
            result dict gains an ``_undo_id``. Return None for "no safe inverse".
            Recording only — execution is an external orchestrator's job.
    """
    _sensitive = set(sensitive_params or [])

    def decorator(func: Any) -> Any:
        # Cache the signature at decoration time so positional args can be
        # mapped to parameter names on every call (audit + env scoping).
        signature = inspect.signature(func)

        if inspect.iscoroutinefunction(func):
            # ── Async tools get an async wrapper with identical audit /
            # policy / circuit-breaker semantics (a sync wrapper would return
            # an un-awaited coroutine and audit it as "ok").
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                state = _CallState(
                    func, args, kwargs, signature, _sensitive, risk_level,
                    timeout_seconds, undo,
                )
                try:
                    _pre_check(state)
                    return _annotate_result(state, await func(*args, **kwargs))
                except (PolicyDenied, BudgetExceeded):
                    raise
                except Exception as exc:
                    _capture_error(state, exc)
                    raise
                finally:
                    _finalize(state)
        else:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                state = _CallState(
                    func, args, kwargs, signature, _sensitive, risk_level,
                    timeout_seconds, undo,
                )
                try:
                    _pre_check(state)
                    return _annotate_result(state, func(*args, **kwargs))
                except (PolicyDenied, BudgetExceeded):
                    raise
                except Exception as exc:
                    _capture_error(state, exc)
                    raise
                finally:
                    _finalize(state)

        # ── Attach metadata for harness / introspection ───────────
        wrapper._is_governed_tool = True
        wrapper._risk_level = risk_level
        wrapper._idempotent = idempotent
        wrapper._timeout_seconds = timeout_seconds
        wrapper._sensitive_params = list(_sensitive)
        return wrapper

    # Support @governed_tool and @governed_tool(...)
    if fn is not None:
        return decorator(fn)
    return decorator


# ── Internal helpers ──────────────────────────────────────────────────


class _CallState:
    """Per-call context shared by the sync and async wrapper bodies.

    Built once per invocation; the helper functions (`_pre_check`,
    `_annotate_result`, `_capture_error`, `_finalize`) read and mutate it so
    both wrappers keep identical audit / policy / circuit-breaker semantics.
    """

    __slots__ = (
        "skill", "tool_name", "agent", "start", "status", "result",
        "policy_result", "pattern_match", "audit", "policy",
        "safe_params", "env", "risk_level", "timeout_seconds",
        "rationale", "approved_by", "risk_tier", "undo",
    )

    def __init__(
        self,
        func: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        signature: inspect.Signature,
        sensitive: set[str],
        risk_level: str,
        timeout_seconds: int,
        undo: Any = None,
    ) -> None:
        self.undo = undo
        self.skill = _infer_skill(func)
        self.tool_name = func.__name__
        self.agent = detect_agent()
        self.start = time.time()
        self.status = "ok"
        self.result: Any = None
        self.policy_result: PolicyResult | None = None
        self.pattern_match: PatternMatch | None = None
        self.risk_level = risk_level
        self.timeout_seconds = timeout_seconds
        self.audit = get_engine()
        self.policy = get_policy_engine()

        # Map positional args to parameter names so they appear in the audit
        # log and participate in env scoping (previously only kwargs did).
        params = _bind_params(signature, args, kwargs)
        self.safe_params = _redact(params, sensitive)
        env = params.get("target", params.get("env", ""))
        self.env = str(env) if env else ""

        # Accountability trail (SOC2 / 等保: who authorized this, and why).
        # Sourced from env so an approval gate / pilot can inject context
        # without changing every tool signature. risk_tier is filled by the
        # policy pre-check (graduated autonomy).
        self.rationale = os.environ.get("OPCUA_AUDIT_RATIONALE", "")
        self.approved_by = os.environ.get("OPCUA_AUDIT_APPROVED_BY", "")
        self.risk_tier = ""


def _bind_params(
    signature: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Build a full name→value param dict from positional + keyword args.

    Falls back to kwargs-only if binding fails (the actual call will raise
    the matching TypeError; audit should not mask it with its own).
    """
    try:
        bound = signature.bind_partial(*args, **kwargs)
        # Apply declared defaults so env scoping and risk-tier matching see the
        # effective target/tags even when the caller relied on a default value
        # (bind_partial alone only captures explicitly-passed arguments).
        bound.apply_defaults()
    except TypeError:
        return dict(kwargs)
    params: dict[str, Any] = {}
    for name, value in bound.arguments.items():
        kind = signature.parameters[name].kind
        if kind == inspect.Parameter.VAR_KEYWORD:
            params.update(value)
        elif kind == inspect.Parameter.VAR_POSITIONAL:
            params[name] = list(value)
        else:
            params[name] = value
    return params


def _pre_check(state: _CallState) -> None:
    """Policy pre-check + L5 auto-remediation pattern consult.

    Raises PolicyDenied when policy denies the call. Pattern engine failures
    never block the call (fail-open by design — a broken pattern file must
    not take down every MCP tool).
    """
    state.policy_result = state.policy.check_allowed(
        state.tool_name,
        env=state.env,
        risk_level=state.risk_level,
        params=state.safe_params,
    )
    if not state.policy_result.allowed:
        state.status = "denied"
        state.result = {
            "error": state.policy_result.reason,
            "rule": state.policy_result.rule,
        }
        raise PolicyDenied(state.policy_result)

    # Graduated autonomy — what approval tier does this op need? Record it on
    # the audit trail, and enforce: tiers that require a named approver (dual /
    # review) are denied when none was recorded (OPCUA_AUDIT_APPROVED_BY).
    tier = state.policy.required_approval_tier(
        state.tool_name,
        env=state.env,
        risk_level=state.risk_level,
        params=state.safe_params,
    )
    state.risk_tier = tier.tier
    if tier.requires_approver and not state.approved_by:
        reason = (
            f"Operation '{state.tool_name}' on '{state.env or 'target'}' requires "
            f"'{tier.tier}' approval (rule: {tier.rule}) but no approver is recorded. "
            f"Set OPCUA_AUDIT_APPROVED_BY to the authorizing human (and "
            f"OPCUA_AUDIT_RATIONALE to why) before retrying."
        )
        if tier.reason:
            reason += f" Policy note: {tier.reason}"
        denial = PolicyResult(allowed=False, rule=f"approval_tier:{tier.tier}", reason=reason)
        state.policy_result = denial
        state.status = "denied"
        state.result = {"error": reason, "rule": denial.rule}
        raise PolicyDenied(denial)

    # Budget / runaway guard — only for calls policy already allowed, so denied
    # calls do not count. A trip raises BudgetExceeded (a hard stop); record the
    # denial on state so _finalize audits it.
    try:
        get_budget().check_and_record(state.tool_name, state.safe_params)
    except BudgetExceeded as exc:
        state.status = "budget_exceeded"
        state.result = {"error": exc.reason, "rule": exc.rule}
        raise

    try:
        state.pattern_match = get_pattern_engine().match(
            skill=state.skill, tool=state.tool_name, target=state.env
        )
    except Exception:  # noqa: BLE001 — fail-open by design
        state.pattern_match = None


def _annotate_result(state: _CallState, result: Any) -> Any:
    """Record the result, surface pattern context, and record an undo token.

    Runs only on the success path (the wrapper calls it with the function's
    return value), so a recorded undo always corresponds to a change that
    actually happened.
    """
    state.result = result
    if (
        state.pattern_match
        and state.pattern_match.armed
        and isinstance(result, dict)
    ):
        result.setdefault("_pattern_id", state.pattern_match.pattern.pattern_id)
        result.setdefault("_pattern_armed", True)
    _record_undo(state, result)
    return result


def _record_undo(state: _CallState, result: Any) -> None:
    """Compute and persist the inverse descriptor for a successful write.

    Best-effort: a broken undo callable or store must never fail the call.
    Attaches ``_undo_id`` to dict results so the agent / pilot can reference it.
    """
    if state.undo is None:
        return
    try:
        descriptor = state.undo(state.safe_params, result)
    except Exception:  # noqa: BLE001 — undo computation must not fail the call
        _log.warning("undo callable for %s.%s raised", state.skill, state.tool_name,
                     exc_info=True)
        return
    if not descriptor:
        return
    try:
        from iaiops.core.governance.undo import get_undo_store

        undo_id = get_undo_store().record(
            skill=state.skill,
            tool=state.tool_name,
            undo_descriptor=descriptor,
            orig_params=state.safe_params,
        )
        if undo_id and isinstance(result, dict):
            result.setdefault("_undo_id", undo_id)
    except Exception:  # noqa: BLE001 — recording is best-effort
        _log.warning("failed to record undo for %s.%s", state.skill, state.tool_name,
                     exc_info=True)


def _capture_error(state: _CallState, exc: Exception) -> None:
    """Record a failed call. Exception text and tracebacks can carry
    connection strings, credentials, internal paths — sanitize before
    persisting to the audit row."""
    state.status = "error"
    state.result = {
        "error": sanitize(_redact_secrets_text(str(exc)), 500),
        "traceback": sanitize(
            _redact_secrets_text(traceback.format_exc()[-500:]), 500
        ),
    }


def _finalize(state: _CallState) -> None:
    """Audit + circuit-breaker bookkeeping. Runs in the wrapper's finally."""
    duration = int((time.time() - state.start) * 1000)

    # Accumulate wall-time toward the cumulative time budget (best-effort).
    try:
        get_budget().add_duration(time.time() - state.start)
    except Exception:  # noqa: BLE001 — bookkeeping must never fail the call
        pass

    # timeout_seconds is advisory: exceeding it logs a warning, no hard
    # cancellation (cancelling mid-flight network calls is worse).
    if state.timeout_seconds and duration > state.timeout_seconds * 1000:
        _log.warning(
            "%s.%s took %dms — exceeded timeout_seconds=%d (advisory, not cancelled)",
            state.skill, state.tool_name, duration, state.timeout_seconds,
        )

    bypassed = state.policy_result and state.policy_result.rule == "policy_disabled"
    final_status = f"{state.status}_bypassed" if bypassed else state.status

    # Update circuit-breaker state for armed patterns
    if state.pattern_match and state.pattern_match.armed:
        try:
            get_pattern_engine().report_outcome(
                pattern_id=state.pattern_match.pattern.pattern_id,
                target=state.env,
                success=(state.status == "ok"),
            )
        except Exception:  # noqa: BLE001 — never let bookkeeping fail the call
            pass

    pattern_id = state.pattern_match.pattern.pattern_id if state.pattern_match else ""
    pattern_armed = bool(state.pattern_match and state.pattern_match.armed)

    state.audit.log(
        skill=state.skill,
        tool=state.tool_name,
        params=state.safe_params,
        result=_with_pattern_context(state.result, pattern_id, pattern_armed),
        status=final_status,
        duration_ms=duration,
        agent=state.agent,
        user="",
        risk_level=state.risk_level,
        rationale=state.rationale,
        approved_by=state.approved_by,
        risk_tier=state.risk_tier,
    )


def _infer_skill(func: Any) -> str:
    """Infer the skill name from the function's module path.

    ``iaiops.connectors.opcua.ops`` → ``iaiops``
    ``mcp_server.server`` → ``iaiops`` (the only consumer here).
    """
    module = getattr(func, "__module__", "") or ""
    if module.startswith("iaiops") or module.startswith("mcp_server"):
        return "iaiops"
    return "unknown"


def _redact(params: dict[str, Any], sensitive: set[str]) -> dict[str, Any]:
    """Return a copy of params with sensitive values replaced by '***'.

    Recurses into nested dicts AND lists/tuples so credentials buried inside
    collections (e.g. ``{"targets": [{"password": "x"}]}``) are redacted too.
    """
    if not sensitive:
        return params
    result: dict[str, Any] = {}
    for k, v in params.items():
        if k in sensitive:
            result[k] = "***"
        else:
            result[k] = _redact_value(v, sensitive)
    return result


def _redact_value(value: Any, sensitive: set[str]) -> Any:
    """Recursively redact sensitive keys inside dicts, lists, and tuples."""
    if isinstance(value, dict):
        return _redact(value, sensitive)
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(item, sensitive) for item in value)
    return value


# Matches ``key=value`` / ``key: value`` / ``key"="value`` for common secret
# keys in free-form exception text. Value runs until whitespace, quote, comma,
# or '@' (to keep host:port that often follows a credential in DSNs).
_SECRET_TEXT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|bearer)"
    r"(\s*[=:]\s*|\s+)"
    r"['\"]?[^\s'\",@]+",
)


def _redact_secrets_text(text: str) -> str:
    """Redact ``password=...`` / ``token: ...`` style secrets in free-form text."""
    return _SECRET_TEXT_RE.sub(r"\1\2***", text)


def _with_pattern_context(result: Any, pattern_id: str, armed: bool) -> Any:
    """Attach pattern metadata to an audit row's result field.

    Only mutates dict results; non-dict results (errors, primitives) are
    returned unchanged so the audit log preserves them faithfully.
    """
    if not pattern_id:
        return result
    if isinstance(result, dict):
        annotated = dict(result)
        annotated.setdefault("_pattern_id", pattern_id)
        annotated.setdefault("_pattern_armed", armed)
        return annotated
    return result
