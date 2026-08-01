"""A caller that retries a denied write forever must eventually be stopped.

The budget does two different jobs and a policy denial separates them:

* the **ceilings** (calls, wall-time) price work. A denied call did none, so it is
  deliberately free of them — otherwise a misconfigured deny rule could exhaust an
  operator's budget without a single operation running.
* the **runaway guard** detects a stuck loop.

The fingerprint was recorded only on the allowed path, so the guard could see every
loop except the most likely one: an agent that does not understand a denial and
retries it. Measured before the fix — 500 identical denied high-risk writes against
a call ceiling of 10 produced **zero** stops, and 500 audit rows.

These tests pin the fix and, just as importantly, pin what the fix must NOT do: a
denial still costs nothing against the ceilings.
"""

from __future__ import annotations

import pytest

from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.budget import BudgetExceeded, get_budget, reset_budget
from iaiops.core.governance.decorators import PolicyDenied, governed_tool
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine

_RUNAWAY_MAX = 5


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.setenv("OPCUA_RUNAWAY_MAX", str(_RUNAWAY_MAX))
    monkeypatch.setenv("OPCUA_MAX_TOOL_CALLS", "1000")
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    reset_engine()
    reset_policy_engine()
    reset_budget()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")
    yield
    reset_engine()
    reset_policy_engine()
    reset_budget()


@pytest.fixture
def denied_write():
    """A high-risk write with no approver recorded — denied on every call."""

    @governed_tool(risk_level="high", preview_param="dry_run")
    def w(dry_run: bool = True) -> dict:
        return {"applied": True}

    return w


def _hammer(fn, limit: int = 100) -> tuple[int, str]:
    """Retry until something stops us. Returns (denials seen, stopping rule)."""
    denials = 0
    for _ in range(limit):
        try:
            fn(dry_run=False)
        except PolicyDenied:
            denials += 1
        except BudgetExceeded as exc:
            return denials, exc.rule
    return denials, ""


@pytest.mark.unit
def test_retrying_a_denied_write_is_eventually_stopped(denied_write) -> None:
    denials, rule = _hammer(denied_write)
    assert rule == "budget_runaway", f"the loop was never stopped ({denials} denials)"
    assert denials == _RUNAWAY_MAX


@pytest.mark.unit
def test_denials_still_cost_nothing_against_the_ceilings(denied_write) -> None:
    """The property the fix must not break: a denied call did no work, so it must
    not consume the call budget. A misconfigured deny rule that could drain an
    operator's ceiling would be a worse failure than the loop."""
    _hammer(denied_write)
    assert get_budget().snapshot()["total_calls"] == 0


@pytest.mark.unit
def test_a_single_denial_is_still_free(denied_write) -> None:
    """Being denied once must stay ordinary — no warning, no counter to explain."""
    with pytest.raises(PolicyDenied):
        denied_write(dry_run=False)
    snapshot = get_budget().snapshot()
    assert snapshot["total_calls"] == 0
    assert get_engine().query(tool="w")[-1]["status"] == "denied"


@pytest.mark.unit
def test_the_stop_is_audited_as_a_budget_trip_not_a_denial(denied_write) -> None:
    """An operator reading the trail must be able to tell "you were denied" from
    "you were denied and then would not stop asking"."""
    _hammer(denied_write)
    statuses = [row["status"] for row in get_engine().query(tool="w")]
    assert statuses[0] == "budget_exceeded", "the stop must be distinguishable"
    assert statuses.count("denied") == _RUNAWAY_MAX


@pytest.mark.unit
def test_different_arguments_are_not_the_same_loop() -> None:
    """The guard is per (tool, params). An operator working through many distinct
    denied targets is not looping, and must not be stopped as though they were."""
    budget = get_budget()
    for i in range(_RUNAWAY_MAX * 3):
        budget.check_runaway("w", {"endpoint": f"plc{i}"})  # must not raise


@pytest.mark.unit
def test_allowed_calls_and_denials_share_one_window(denied_write) -> None:
    """Alternating an allowed call with a denied one must not reset the loop
    detector — the fingerprints differ, so this pins that the two paths feed the
    same structure rather than two independent ones."""
    budget = get_budget()
    for _ in range(_RUNAWAY_MAX):
        budget.check_runaway("probe", {"a": 1})
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.check_and_record("probe", {"a": 1})
    assert excinfo.value.rule == "budget_runaway"
