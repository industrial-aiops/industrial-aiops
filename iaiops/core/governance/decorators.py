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

from iaiops.core.governance.approvals import consume_approval
from iaiops.core.governance.audit import detect_agent, get_engine
from iaiops.core.governance.budget import BudgetExceeded, get_budget
from iaiops.core.governance.patterns import PatternMatch, get_pattern_engine
from iaiops.core.governance.policy import PolicyResult, get_policy_engine
from iaiops.core.governance.sanitize import sanitize

_log = logging.getLogger("iaiops.decorators")

# Risk levels for which governance fails CLOSED (audit must be writable,
# approver tiers enforced even under the policy kill switch).
_FAIL_CLOSED_RISK = ("high", "critical")

_env_approver_warned = False
_audit_degraded_warned = False


def _warn_env_approver_once() -> None:
    """Warn (once per process) that the static env-var approver is in use."""
    global _env_approver_warned
    if not _env_approver_warned:
        _env_approver_warned = True
        _log.warning(
            "Approver taken from OPCUA_AUDIT_APPROVED_BY env var — this is a "
            "STATIC approval that authorizes every call while set. Prefer "
            "one-shot tokens: iaiops approve <tool> --endpoint <ep> --by <name>.",
        )


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
    egress: bool = False,
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
        egress: Whether the tool transmits local/plant data to a destination the
            CALLER names (a message bus, an external historian, a remote model
            endpoint). Metadata only — this decorator never blocks on it; the
            ``IAIOPS_NO_EGRESS`` registration gate reads ``_egress`` to withhold
            such tools from the MCP registry (see ``mcp_server/noegress.py``).
            Orthogonal to ``risk_level``: a tool can ship data off-box without
            changing any plant state (``historian_push`` is low-risk egress), and
            a high-risk write need not egress anything. Defaults to False, and a
            tool decorated by an older copy of this module simply has no
            ``_egress`` attribute — readers must treat that as False.

            NOT egress: a protocol write to a plant device (that is what
            ``risk_level`` and ``IAIOPS_READ_ONLY`` govern), a read that happens
            to open an outbound socket, or a write to a local file.
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
                    func,
                    args,
                    kwargs,
                    signature,
                    _sensitive,
                    risk_level,
                    timeout_seconds,
                    undo,
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
                    func,
                    args,
                    kwargs,
                    signature,
                    _sensitive,
                    risk_level,
                    timeout_seconds,
                    undo,
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
        wrapper._egress = bool(egress)
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
        "skill",
        "tool_name",
        "agent",
        "start",
        "status",
        "result",
        "policy_result",
        "pattern_match",
        "audit",
        "policy",
        "safe_params",
        "env",
        "risk_level",
        "timeout_seconds",
        "rationale",
        "approved_by",
        "approver_source",
        "risk_tier",
        "undo",
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
        # Control-char scrub of param values (recursively) before they land in
        # the audit row / SIEM forward — device-sourced strings can carry
        # terminal escapes.
        self.safe_params = _sanitize_params(_redact(params, sensitive))
        # Endpoint/environment selector: MCP tools name it ``endpoint``;
        # ``target``/``env`` kept first for existing callers. A None value
        # (e.g. ``endpoint=None`` default) resolves to "".
        env = params.get("target", params.get("env", params.get("endpoint", "")))
        self.env = str(env) if env else ""

        # Accountability trail (SOC2 / 等保: who authorized this, and why).
        # Sourced from env so an approval gate / pilot can inject context
        # without changing every tool signature. risk_tier is filled by the
        # policy pre-check (graduated autonomy).
        self.rationale = os.environ.get("OPCUA_AUDIT_RATIONALE", "")
        self.approved_by = os.environ.get("OPCUA_AUDIT_APPROVED_BY", "")
        self.approver_source = "env" if self.approved_by else ""
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

    # Audit availability gate — high/critical-risk tools MUST leave an audit
    # trail. When the audit DB cannot be written, deny them (fail closed);
    # low/medium reads proceed with a once-per-process warning (availability
    # over auditability for reads). Checked BEFORE approval-token consumption
    # so a one-shot token is not burned on a call that will be denied.
    _check_audit_health(state)

    # Graduated autonomy — what approval tier does this op need? Record it on
    # the audit trail, and enforce: tiers that require a named approver (dual /
    # review) are denied when none was recorded. Approvers come from a one-shot
    # token (``iaiops approve``, consumed on use) or, as a deprecated static
    # fallback, the OPCUA_AUDIT_APPROVED_BY env var.
    tier = state.policy.required_approval_tier(
        state.tool_name,
        env=state.env,
        risk_level=state.risk_level,
        params=state.safe_params,
    )
    state.risk_tier = tier.tier
    if tier.requires_approver:
        _resolve_approver(state, tier)

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


def _check_audit_health(state: _CallState) -> None:
    """Deny high/critical-risk calls when the audit trail cannot be written."""
    global _audit_degraded_warned
    if state.audit.healthy:
        return
    if state.risk_level in _FAIL_CLOSED_RISK:
        reason = (
            f"Operation '{state.tool_name}' is {state.risk_level}-risk but the "
            f"audit log cannot be written — denied (fail closed). Restore the "
            f"audit DB (see 'iaiops doctor' / IAIOPS_HOME) before retrying."
        )
        denial = PolicyResult(allowed=False, rule="audit_unavailable", reason=reason)
        state.policy_result = denial
        state.status = "denied"
        state.result = {"error": reason, "rule": denial.rule}
        raise PolicyDenied(denial)
    if not _audit_degraded_warned:
        _audit_degraded_warned = True
        _log.warning(
            "Audit log is unavailable — low/medium-risk calls proceed WITHOUT "
            "an audit trail; high/critical-risk calls are denied until it is "
            "restored.",
        )


def _resolve_approver(state: _CallState, tier: Any) -> None:
    """Fill state.approved_by for an approver-gated tier, or deny.

    Precedence: a matching one-shot approval token (consumed on use,
    ``approver_source="token"``) wins over the deprecated static
    OPCUA_AUDIT_APPROVED_BY env var (``approver_source="env"``, warned once).
    """
    approval = None
    try:
        approval = consume_approval(state.tool_name, state.env)
    except Exception:  # noqa: BLE001 — token-store trouble falls back to env/deny
        _log.warning("Approval token lookup failed for %s", state.tool_name, exc_info=True)
    if approval is not None:
        state.approved_by = approval.approved_by
        state.approver_source = "token"
        if approval.rationale and not state.rationale:
            state.rationale = approval.rationale
        return
    if state.approved_by:
        state.approver_source = "env"
        _warn_env_approver_once()
        return

    reason = (
        f"Operation '{state.tool_name}' on '{state.env or 'target'}' requires "
        f"'{tier.tier}' approval (rule: {tier.rule}) but no approver is recorded. "
        f"Grant a one-shot approval first: iaiops approve {state.tool_name}"
        + (f" --endpoint {state.env}" if state.env else "")
        + " --by <approver> [--ttl 600]."
    )
    if tier.reason:
        reason += f" Policy note: {tier.reason}"
    denial = PolicyResult(allowed=False, rule=f"approval_tier:{tier.tier}", reason=reason)
    state.policy_result = denial
    state.status = "denied"
    state.result = {"error": reason, "rule": denial.rule}
    raise PolicyDenied(denial)


def _annotate_result(state: _CallState, result: Any) -> Any:
    """Record the result, surface pattern context, and record an undo token.

    Runs only on the success path (the wrapper calls it with the function's
    return value), so a recorded undo always corresponds to a change that
    actually happened.
    """
    state.result = result
    if state.pattern_match and state.pattern_match.armed and isinstance(result, dict):
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
        _log.warning("undo callable for %s.%s raised", state.skill, state.tool_name, exc_info=True)
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
        _log.warning("failed to record undo for %s.%s", state.skill, state.tool_name, exc_info=True)


def _capture_error(state: _CallState, exc: Exception) -> None:
    """Record a failed call. Exception text and tracebacks can carry
    connection strings, credentials, internal paths — sanitize before
    persisting to the audit row."""
    state.status = "error"
    state.result = {
        "error": sanitize(_redact_secrets_text(str(exc)), 500),
        "traceback": sanitize(_redact_secrets_text(traceback.format_exc()[-500:]), 500),
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
            state.skill,
            state.tool_name,
            duration,
            state.timeout_seconds,
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

    written = state.audit.log(
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
        approver_source=state.approver_source if state.approved_by else "",
    )
    if not written and state.risk_level in _FAIL_CLOSED_RISK:
        # The pre-check gates high-risk calls on audit health, so reaching
        # here means the DB failed mid-call. Surface loudly — the operation
        # already ran, so raising would only mask its outcome.
        _log.error(
            "AUDIT WRITE FAILED for %s-risk call %s.%s (status=%s) — the "
            "operation executed but left NO audit row. Investigate the audit "
            "DB immediately.",
            state.risk_level,
            state.skill,
            state.tool_name,
            final_status,
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


# Generous cap for param text: long node lists are legitimate, but an audit
# row should never carry unbounded attacker-controlled text either.
_PARAM_TEXT_MAX = 4096


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of params with control characters stripped from strings.

    Param values can carry device/network-sourced text (node ids, payloads,
    error strings); terminal escapes and C0/C1 controls in them would land
    verbatim in the audit row and flow on to SIEM forwards. Recurses into
    dicts/lists/tuples and always builds new objects (inputs not mutated).
    """
    return {k: _sanitize_value(v) for k, v in params.items()}


def _sanitize_value(value: Any) -> Any:
    """Recursively scrub control chars from string values inside collections."""
    if isinstance(value, str):
        return sanitize(value, _PARAM_TEXT_MAX)
    if isinstance(value, dict):
        return _sanitize_params(value)
    if isinstance(value, (list, tuple)):
        return type(value)(_sanitize_value(item) for item in value)
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
