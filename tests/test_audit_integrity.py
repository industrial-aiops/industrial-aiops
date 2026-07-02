"""Audit-log integrity tests: hash chain + verify (M-4) and fail-closed
behavior for high-risk calls when the audit trail is unavailable (M-3)."""

from __future__ import annotations

import sqlite3

import pytest

from iaiops.core.governance.audit import (
    AuditEngine,
    get_engine,
    reset_engine,
)
from iaiops.core.governance.decorators import PolicyDenied, governed_tool
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    monkeypatch.delenv("IAIOPS_POLICY_DISABLED", raising=False)
    monkeypatch.delenv("OPCUA_POLICY_DISABLED", raising=False)
    reset_engine()
    reset_policy_engine()
    yield
    reset_engine()
    reset_policy_engine()


def _seed(engine: AuditEngine, n: int) -> None:
    for i in range(n):
        assert engine.log(skill="iaiops", tool=f"tool_{i}", params={"i": i}, status="ok")


# ── M-4: hash chain ───────────────────────────────────────────────────


@pytest.mark.unit
def test_chain_verifies_clean(tmp_path):
    engine = AuditEngine(tmp_path / "audit.db")
    _seed(engine, 5)
    result = engine.verify_chain()
    assert result == {"ok": True, "checked": 5, "unhashed": 0}


@pytest.mark.unit
def test_rows_are_chained(tmp_path):
    engine = AuditEngine(tmp_path / "audit.db")
    _seed(engine, 3)
    rows = engine.query(limit=10)  # DESC order
    rows.reverse()
    assert rows[0]["prev_hash"] == ""
    assert rows[1]["prev_hash"] == rows[0]["row_hash"]
    assert rows[2]["prev_hash"] == rows[1]["row_hash"]
    assert all(len(r["row_hash"]) == 64 for r in rows)


@pytest.mark.unit
def test_tampered_field_detected(tmp_path):
    db = tmp_path / "audit.db"
    engine = AuditEngine(db)
    _seed(engine, 3)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE audit_log SET params = '{\"i\": 999}' WHERE id = 2")
    conn.commit()
    conn.close()
    result = engine.verify_chain()
    assert not result["ok"]
    assert result["first_broken_id"] == 2
    assert "modified" in result["reason"]


@pytest.mark.unit
def test_deleted_row_detected(tmp_path):
    db = tmp_path / "audit.db"
    engine = AuditEngine(db)
    _seed(engine, 3)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM audit_log WHERE id = 2")
    conn.commit()
    conn.close()
    result = engine.verify_chain()
    assert not result["ok"]
    assert result["first_broken_id"] == 3


@pytest.mark.unit
def test_legacy_rows_migrate_and_chain_starts_after_them(tmp_path):
    """A pre-chain DB gains the columns; old rows count as unhashed."""
    db = tmp_path / "audit.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, skill TEXT NOT NULL, tool TEXT NOT NULL,
            params TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ok', duration_ms INTEGER NOT NULL DEFAULT 0,
            agent TEXT NOT NULL DEFAULT 'unknown', workflow_id TEXT NOT NULL DEFAULT '',
            user TEXT NOT NULL DEFAULT 'unknown', risk_level TEXT NOT NULL DEFAULT 'low'
        )"""
    )
    conn.execute(
        "INSERT INTO audit_log (ts, skill, tool) VALUES ('2025-01-01', 'iaiops', 'old')"
    )
    conn.commit()
    conn.close()

    engine = AuditEngine(db)
    assert engine.log(skill="iaiops", tool="new_tool", status="ok")
    result = engine.verify_chain()
    assert result["ok"]
    assert result["unhashed"] == 1
    assert result["checked"] == 1


# ── M-3: audit health / fail-closed ───────────────────────────────────


@pytest.mark.unit
def test_healthy_true_for_working_db(tmp_path):
    engine = AuditEngine(tmp_path / "audit.db")
    assert engine.healthy


@pytest.mark.unit
def test_unwritable_db_is_unhealthy_and_log_returns_false(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", "utf-8")
    engine = AuditEngine(blocker / "audit.db")  # parent is a file → init fails
    assert not engine.healthy
    assert engine.log(skill="iaiops", tool="x") is False


def _bad_audit_singleton(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", "utf-8")
    reset_engine()
    return get_engine(blocker / "audit.db")


@pytest.mark.unit
def test_high_risk_denied_when_audit_unavailable(tmp_path):
    _bad_audit_singleton(tmp_path)
    get_policy_engine(tmp_path / "rules.yaml")

    @governed_tool(risk_level="high")
    def dangerous_write(target: str = "plant") -> dict:
        return {"ok": True}

    with pytest.raises(PolicyDenied) as excinfo:
        dangerous_write()
    assert excinfo.value.result.rule == "audit_unavailable"


@pytest.mark.unit
def test_low_risk_proceeds_when_audit_unavailable(tmp_path):
    _bad_audit_singleton(tmp_path)
    get_policy_engine(tmp_path / "rules.yaml")

    @governed_tool(risk_level="low")
    def harmless_read(target: str = "plant") -> dict:
        return {"value": 42}

    assert harmless_read() == {"value": 42}


@pytest.mark.unit
def test_governed_call_lands_in_chain(tmp_path):
    audit = get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")

    @governed_tool(risk_level="low")
    def read_tag(target: str = "plant") -> dict:
        return {"value": 1}

    read_tag()
    assert audit.verify_chain()["ok"]
    rows = audit.query(tool="read_tag")
    assert rows and rows[0]["row_hash"]
