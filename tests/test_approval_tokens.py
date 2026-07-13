"""One-shot approval token tests (M-2): store semantics and decorator wiring."""

from __future__ import annotations

import json
import os
import stat
import time

import pytest

from iaiops.core.governance import decorators as decorators_mod
from iaiops.core.governance.approvals import (
    consume_approval,
    record_approval,
    token_path,
)
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


# ── store semantics ───────────────────────────────────────────────────


@pytest.mark.unit
def test_record_and_consume_roundtrip():
    record_approval("write_coil", "plant1", approved_by="alice", rationale="MOC-42")
    approval = consume_approval("write_coil", "plant1")
    assert approval is not None
    assert approval.approved_by == "alice"
    assert approval.rationale == "MOC-42"
    # One-shot: consumed token is gone.
    assert consume_approval("write_coil", "plant1") is None
    assert not token_path("write_coil", "plant1").exists()


@pytest.mark.unit
def test_token_is_endpoint_scoped():
    record_approval("write_coil", "plant1", approved_by="alice")
    assert consume_approval("write_coil", "plant2") is None
    assert consume_approval("other_tool", "plant1") is None
    assert consume_approval("write_coil", "plant1") is not None


@pytest.mark.unit
def test_expired_token_rejected_and_removed():
    record_approval("write_coil", "plant1", approved_by="alice", ttl_seconds=60)
    path = token_path("write_coil", "plant1")
    data = json.loads(path.read_text("utf-8"))
    data["created_at"] = time.time() - 3600
    path.write_text(json.dumps(data), "utf-8")

    assert consume_approval("write_coil", "plant1") is None
    assert not path.exists()


@pytest.mark.unit
def test_corrupt_token_rejected_and_removed():
    record_approval("write_coil", "plant1", approved_by="alice")
    path = token_path("write_coil", "plant1")
    path.write_text("{not json", "utf-8")
    assert consume_approval("write_coil", "plant1") is None
    assert not path.exists()


@pytest.mark.unit
def test_input_validation():
    with pytest.raises(ValueError):
        record_approval("", "plant1", approved_by="alice")
    with pytest.raises(ValueError):
        record_approval("write_coil", "plant1", approved_by="  ")
    with pytest.raises(ValueError):
        record_approval("write_coil", "plant1", approved_by="alice", ttl_seconds=0)


@pytest.mark.unit
def test_token_file_permissions_0600():
    record_approval("write_coil", "plant1", approved_by="alice")
    path = token_path("write_coil", "plant1")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700


# ── decorator wiring ──────────────────────────────────────────────────


def _make_write_tool():
    @governed_tool(risk_level="high")
    def write_setpoint(value: int, target: str = "plant1") -> dict:
        return {"written": value}

    return write_setpoint


@pytest.mark.unit
def test_gated_call_denied_without_approval():
    tool = _make_write_tool()
    with pytest.raises(PolicyDenied) as excinfo:
        tool(5)
    assert "iaiops approve" in excinfo.value.result.reason


@pytest.mark.unit
def test_token_authorizes_exactly_one_call(tmp_path):
    tool = _make_write_tool()
    record_approval("write_setpoint", "plant1", approved_by="alice", rationale="MOC-7")

    assert tool(5) == {"written": 5}
    rows = get_engine().query(tool="write_setpoint", status="ok")
    assert rows[0]["approved_by"] == "alice"
    assert rows[0]["approver_source"] == "token"
    assert rows[0]["rationale"] == "MOC-7"

    # Second call: token was consumed → denied again.
    with pytest.raises(PolicyDenied):
        tool(6)


@pytest.mark.unit
def test_env_var_fallback_audited_as_env_source(monkeypatch, caplog):
    tool = _make_write_tool()
    monkeypatch.setenv("OPCUA_AUDIT_APPROVED_BY", "bob")
    with caplog.at_level("WARNING", logger="iaiops.decorators"):
        assert tool(7) == {"written": 7}
    rows = get_engine().query(tool="write_setpoint", status="ok")
    assert rows[0]["approved_by"] == "bob"
    assert rows[0]["approver_source"] == "env"
    assert any("STATIC approval" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_token_wins_over_env_var(monkeypatch):
    tool = _make_write_tool()
    monkeypatch.setenv("OPCUA_AUDIT_APPROVED_BY", "bob")
    record_approval("write_setpoint", "plant1", approved_by="alice")
    assert tool(8) == {"written": 8}
    rows = get_engine().query(tool="write_setpoint", status="ok")
    assert rows[0]["approved_by"] == "alice"
    assert rows[0]["approver_source"] == "token"


@pytest.mark.unit
def test_approve_cli_writes_token(tmp_path):
    from typer.testing import CliRunner

    from iaiops.cli._root import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "approve",
            "write_setpoint",
            "--endpoint",
            "plant1",
            "--by",
            "carol",
            "--ttl",
            "120",
            "--rationale",
            "MOC-9",
        ],
    )
    assert result.exit_code == 0, result.output
    approval = consume_approval("write_setpoint", "plant1")
    assert approval is not None and approval.approved_by == "carol"
