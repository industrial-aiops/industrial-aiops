"""Per-process tool-call budget + runaway-loop circuit breaker.

Implements the 2026 agentic-ops "termination condition" / "hard budget"
guardrail. An LLM agent that loops a tool (polling a long task, retrying a
flaky call) otherwise consumes unbounded calls and wall-time — exactly the
failure mode behind the "deleting one snapshot burned 26k tokens over 30 min"
incident. Two layers, both enforced from the ``@governed_tool`` pre-check:

1. **Hard ceilings (opt-in via env).** Total tool calls and cumulative
   wall-time per process. ``OPCUA_MAX_TOOL_CALLS`` / ``OPCUA_MAX_TOOL_SECONDS``.
   Unset (the default) means no ceiling — existing behavior is unchanged.

2. **Runaway breaker (on by default).** The same ``(tool, params)`` called more
   than ``OPCUA_RUNAWAY_MAX`` times within ``OPCUA_RUNAWAY_WINDOW_SEC`` trips a
   short cooldown. Catches a tight poll/retry loop without affecting normal,
   varied tool use. Defaults are generous (25 identical calls in 120s).

Exceeding any limit raises :class:`BudgetExceeded`, a :class:`PolicyDenied`
subclass so the decorator and downstream handlers treat it as a denial carrying
a teaching message (and audit it as a denied call). The exception is a *hard
stop*: it forces the agent to break out of the loop rather than keep spending.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from iaiops.core.governance.policy import PolicyResult

__all__ = ["BudgetExceeded", "BudgetTracker", "get_budget", "reset_budget"]


# Defaults — chosen so normal use never trips them, but a runaway loop does.
_DEFAULT_RUNAWAY_MAX = 25
_DEFAULT_RUNAWAY_WINDOW_SEC = 120


class BudgetExceeded(Exception):
    """Raised when a tool call would exceed a budget / runaway limit.

    Subclasses nothing network-specific; the decorator wraps it into a
    PolicyResult so it shares the existing denial audit path. Kept as its own
    type (not raw PolicyDenied) so callers can catch budget stops distinctly.
    """

    def __init__(self, reason: str, rule: str = "budget") -> None:
        self.reason = reason
        self.rule = rule
        # A PolicyResult mirrors what the policy engine returns on denial, so
        # the decorator can treat budget stops and policy denials uniformly.
        self.policy_result = PolicyResult(allowed=False, rule=rule, reason=reason)
        super().__init__(reason)


def _env_int(name: str, default: int | None) -> int | None:
    """Read an int budget limit from env, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class _State:
    total_calls: int = 0
    total_seconds: float = 0.0
    # fingerprint -> sliding window of epoch-second timestamps
    windows: dict[str, deque] = field(default_factory=dict)


class BudgetTracker:
    """Thread-safe per-process budget + runaway guard.

    Limits are read from the environment on every check so they can be raised
    mid-session (e.g. an operator sets ``OPCUA_RUNAWAY_MAX`` higher) without a
    restart. State is in-memory and per process — it resets when the MCP server
    restarts, which is the correct scope for a single agent session.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = _State()

    # ── Limits (read live from env) ───────────────────────────────────

    @staticmethod
    def _max_calls() -> int | None:
        return _env_int("OPCUA_MAX_TOOL_CALLS", None)

    @staticmethod
    def _max_seconds() -> int | None:
        return _env_int("OPCUA_MAX_TOOL_SECONDS", None)

    @staticmethod
    def _runaway_max() -> int:
        # 0 or negative disables the runaway breaker.
        return _env_int("OPCUA_RUNAWAY_MAX", _DEFAULT_RUNAWAY_MAX) or 0

    @staticmethod
    def _runaway_window() -> int:
        return _env_int("OPCUA_RUNAWAY_WINDOW_SEC", _DEFAULT_RUNAWAY_WINDOW_SEC) or 0

    # ── Enforcement ───────────────────────────────────────────────────

    def check_and_record(self, tool: str, params: dict | None) -> None:
        """Enforce ceilings + runaway guard, then record this call.

        Raises :class:`BudgetExceeded` before the call proceeds when a limit
        would be crossed. Only called for operations the policy engine already
        allowed, so denied calls do not count against the budget.
        """
        now = time.time()
        fp = _fingerprint(tool, params)
        with self._lock:
            # 1. Hard call ceiling
            max_calls = self._max_calls()
            if max_calls is not None and self._state.total_calls >= max_calls:
                raise BudgetExceeded(
                    f"Tool-call budget reached: {self._state.total_calls} calls "
                    f"(OPCUA_MAX_TOOL_CALLS={max_calls}). Stop and summarize what "
                    f"is done; raise the ceiling only if the work genuinely needs "
                    f"more calls.",
                    rule="budget_calls",
                )

            # 2. Hard wall-time ceiling (cumulative across all tool calls)
            max_seconds = self._max_seconds()
            if max_seconds is not None and self._state.total_seconds >= max_seconds:
                raise BudgetExceeded(
                    f"Cumulative tool wall-time budget reached: "
                    f"{self._state.total_seconds:.0f}s "
                    f"(OPCUA_MAX_TOOL_SECONDS={max_seconds}). Stop and report "
                    f"progress rather than continuing.",
                    rule="budget_seconds",
                )

            # 3. Runaway breaker — same (tool, params) hammered in a short window
            runaway_max = self._runaway_max()
            window = self._runaway_window()
            if runaway_max > 0 and window > 0:
                dq = self._state.windows.get(fp)
                if dq is None:
                    dq = deque()
                    self._state.windows[fp] = dq
                cutoff = now - window
                while dq and dq[0] < cutoff:
                    dq.popleft()
                if len(dq) >= runaway_max:
                    raise BudgetExceeded(
                        f"Runaway guard tripped: '{tool}' called {len(dq)} times "
                        f"with identical arguments in {window}s. This usually means "
                        f"a poll/retry loop is stuck. Stop re-calling — check the "
                        f"operation's status once, or wait, instead of looping. "
                        f"(Raise OPCUA_RUNAWAY_MAX if this is genuinely intended.)",
                        rule="budget_runaway",
                    )
                dq.append(now)

            self._state.total_calls += 1

    def add_duration(self, seconds: float) -> None:
        """Accumulate a completed call's wall-time toward the time ceiling."""
        if seconds <= 0:
            return
        with self._lock:
            self._state.total_seconds += seconds

    def snapshot(self) -> dict:
        """Return a copy of current counters (for CLI / introspection / tests)."""
        with self._lock:
            return {
                "total_calls": self._state.total_calls,
                "total_seconds": round(self._state.total_seconds, 1),
                "tracked_fingerprints": len(self._state.windows),
                "limits": {
                    "max_calls": self._max_calls(),
                    "max_seconds": self._max_seconds(),
                    "runaway_max": self._runaway_max(),
                    "runaway_window_sec": self._runaway_window(),
                },
            }


def _fingerprint(tool: str, params: dict | None) -> str:
    """Stable identity for a (tool, params) pair used by the runaway breaker.

    Uses already-redacted params (secrets are '***'), so the fingerprint is
    stable and safe. Falls back to repr on non-serializable values.
    """
    try:
        body = json.dumps(params or {}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 — fingerprint must never raise
        body = repr(params)
    return f"{tool}|{body}"


# ── Singleton ──────────────────────────────────────────────────────────

_tracker: BudgetTracker | None = None
_tracker_lock = threading.Lock()


def get_budget() -> BudgetTracker:
    """Return the global per-process BudgetTracker singleton."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = BudgetTracker()
    return _tracker


def reset_budget() -> None:
    """Reset the singleton. Tests use this between cases."""
    global _tracker
    with _tracker_lock:
        _tracker = None
