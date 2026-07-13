"""Regression tests: the ``endpoint`` parameter must drive env scoping.

Every MCP tool names its selector parameter ``endpoint``, but ``_CallState``
used to resolve only ``target``/``env`` — so ``state.env`` was always "" and
endpoint-scoped approval tokens (keyed ``sha256(tool\\x1fendpoint)``) could
never match. These tests pin the fix.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from iaiops.core.governance import decorators as decorators_mod
from iaiops.core.governance.approvals import record_approval, token_path
from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.decorators import PolicyDenied, governed_tool
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    monkeypatch.delenv("OPCUA_AUDIT_RATIONALE", raising=False)
    monkeypatch.setattr(decorators_mod, "_env_approver_warned", False)
    reset_engine()
    reset_policy_engine()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")  # missing → builtin default tiers
    yield
    reset_engine()
    reset_policy_engine()


# ── _CallState selector resolution ────────────────────────────────────


def _state_for(func: Any, *args: Any, **kwargs: Any) -> decorators_mod._CallState:
    signature = inspect.signature(func)
    return decorators_mod._CallState(
        func, args, kwargs, signature, set(), "low", 300
    )


def _endpoint_tool(node: str, endpoint: str | None = None) -> dict:
    return {"node": node, "endpoint": endpoint}


@pytest.mark.unit
def test_endpoint_kwarg_resolves_to_env():
    state = _state_for(_endpoint_tool, "ns=2;i=1", endpoint="line1")
    assert state.env == "line1"


@pytest.mark.unit
def test_endpoint_none_resolves_to_empty_string():
    state = _state_for(_endpoint_tool, "ns=2;i=1", endpoint=None)
    assert state.env == ""


@pytest.mark.unit
def test_endpoint_default_none_resolves_to_empty_string():
    state = _state_for(_endpoint_tool, "ns=2;i=1")
    assert state.env == ""


@pytest.mark.unit
def test_target_takes_precedence_over_endpoint():
    def tool(target: str = "", endpoint: str | None = None) -> dict:
        return {}

    state = _state_for(tool, target="plant1", endpoint="line1")
    assert state.env == "plant1"


# ── end-to-end: endpoint-scoped approval tokens ───────────────────────


def _make_endpoint_write_tool():
    @governed_tool(risk_level="high")
    def write_setpoint(value: int, endpoint: str | None = None) -> dict:
        return {"written": value, "endpoint": endpoint}

    return write_setpoint


@pytest.mark.integration
def test_scoped_token_not_consumed_by_other_endpoint():
    tool = _make_endpoint_write_tool()
    record_approval("write_setpoint", "line1", approved_by="alice")

    with pytest.raises(PolicyDenied):
        tool(5, endpoint="line2")
    # The line1 token must survive a denied call against line2.
    assert token_path("write_setpoint", "line1").exists()


@pytest.mark.integration
def test_scoped_token_consumed_by_matching_endpoint():
    tool = _make_endpoint_write_tool()
    record_approval("write_setpoint", "line1", approved_by="alice", rationale="MOC-11")

    assert tool(5, endpoint="line1") == {"written": 5, "endpoint": "line1"}
    assert not token_path("write_setpoint", "line1").exists()

    rows = get_engine().query(tool="write_setpoint", status="ok")
    assert rows[0]["approved_by"] == "alice"
    assert rows[0]["approver_source"] == "token"

    # One-shot: the consumed token does not authorize a second call.
    with pytest.raises(PolicyDenied):
        tool(6, endpoint="line1")


@pytest.mark.integration
def test_denial_message_names_the_endpoint():
    tool = _make_endpoint_write_tool()
    with pytest.raises(PolicyDenied) as excinfo:
        tool(5, endpoint="line1")
    assert "--endpoint line1" in excinfo.value.result.reason
