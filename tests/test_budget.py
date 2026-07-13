"""Tests for the per-process budget / runaway guard (``governance/budget.py``).

The "唯一带预算" selling point: an agent looping a tool must hit a hard stop.
Covers the three enforcement layers (call ceiling, wall-time ceiling, runaway
breaker) directly on ``BudgetTracker.check_and_record`` and end-to-end through
``@governed_tool`` (the only production entry point).
"""

from __future__ import annotations

from typing import Any

import pytest

from iaiops.core.governance.budget import BudgetExceeded, get_budget
from iaiops.core.governance.decorators import governed_tool


@pytest.mark.unit
def test_normal_calls_accumulate_in_snapshot() -> None:
    budget = get_budget()
    for i in range(5):
        budget.check_and_record("read_tag", {"tag": f"t{i}"})
    budget.add_duration(1.5)
    budget.add_duration(2.5)

    snap = budget.snapshot()
    assert snap["total_calls"] == 5
    assert snap["total_seconds"] == 4.0
    assert snap["tracked_fingerprints"] == 5


@pytest.mark.unit
def test_call_ceiling_raises_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPCUA_MAX_TOOL_CALLS", "3")
    budget = get_budget()
    for i in range(3):
        budget.check_and_record("read_tag", {"tag": f"t{i}"})

    with pytest.raises(BudgetExceeded) as exc:
        budget.check_and_record("read_tag", {"tag": "t99"})
    assert exc.value.rule == "budget_calls"
    assert exc.value.policy_result.allowed is False


@pytest.mark.unit
def test_wall_time_ceiling_raises_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPCUA_MAX_TOOL_SECONDS", "10")
    budget = get_budget()
    budget.check_and_record("read_tag", {"tag": "t1"})  # under the ceiling: fine
    budget.add_duration(11.0)

    with pytest.raises(BudgetExceeded) as exc:
        budget.check_and_record("read_tag", {"tag": "t2"})
    assert exc.value.rule == "budget_seconds"


@pytest.mark.unit
def test_runaway_breaker_trips_on_identical_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPCUA_RUNAWAY_MAX", "5")
    budget = get_budget()
    for _ in range(5):
        budget.check_and_record("poll_status", {"job": "j1"})

    with pytest.raises(BudgetExceeded) as exc:
        budget.check_and_record("poll_status", {"job": "j1"})
    assert exc.value.rule == "budget_runaway"

    # Varied params are a different fingerprint — normal use never trips.
    budget.check_and_record("poll_status", {"job": "j2"})


@pytest.mark.unit
def test_runaway_breaker_disabled_when_max_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPCUA_RUNAWAY_MAX", "0")
    budget = get_budget()
    for _ in range(50):
        budget.check_and_record("poll_status", {"job": "j1"})  # never raises


@pytest.mark.unit
def test_governed_tool_enforces_call_ceiling_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ceiling stops a real @governed_tool loop, not just the tracker."""
    monkeypatch.setenv("OPCUA_MAX_TOOL_CALLS", "2")

    @governed_tool(risk_level="low")
    def read_tag(tag: str, target: str = "plant1") -> dict[str, Any]:
        return {"tag": tag, "value": 1}

    assert read_tag("t1")["value"] == 1
    assert read_tag("t2")["value"] == 1
    with pytest.raises(BudgetExceeded) as exc:
        read_tag("t3")
    assert exc.value.rule == "budget_calls"
    assert get_budget().snapshot()["total_calls"] == 2
