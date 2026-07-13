"""End-to-end tests for the undo-token store (``iaiops/core/governance/undo.py``).

The "唯一带回滚" selling point rests on ``@governed_tool(undo=...)`` persisting a
replayable inverse descriptor to ``$IAIOPS_HOME/undo.db`` on every successful
high-risk write. These tests drive a fake high-risk write through the real
decorator under the isolated home (tests/conftest.py) and assert the row is
persisted, ``_undo_id`` is attached, and the store API round-trips.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from iaiops.core.governance.decorators import governed_tool
from iaiops.core.governance.undo import get_undo_store, reset_undo_store


def _inverse(params: dict[str, Any], result: Any) -> dict[str, Any] | None:
    """Standard inverse: rewrite the captured BEFORE value."""
    return {
        "tool": "fake_plc_write",
        "params": {"value": result["previous"], "target": params.get("target", "")},
        "note": "restore pre-write value",
    }


def _make_write(undo: Any) -> Any:
    """Build a governed high-risk write with the given undo declaration."""

    @governed_tool(risk_level="high", undo=undo)
    def fake_plc_write(value: int, target: str = "plant1", dry_run: bool = False) -> dict[str, Any]:
        return {"applied": value, "previous": 7}

    return fake_plc_write


@pytest.fixture
def approver(monkeypatch: pytest.MonkeyPatch) -> None:
    """High-risk ops need a named approver (builtin 'dual' tier) — provide one."""
    monkeypatch.setenv("OPCUA_AUDIT_APPROVED_BY", "test-approver")


@pytest.mark.unit
def test_high_risk_write_persists_undo_row_and_attaches_undo_id(
    approver: None, isolated_iaiops_home: Path
) -> None:
    fake_plc_write = _make_write(_inverse)

    result = fake_plc_write(42, target="plant1", dry_run=False)

    undo_id = result.get("_undo_id")
    assert undo_id, "successful high-risk write must attach _undo_id to its result"
    assert (isolated_iaiops_home / "undo.db").exists(), "undo store must live under IAIOPS_HOME"

    row = get_undo_store().get(undo_id)
    assert row is not None, "recorded undo row must be retrievable by id"
    assert row["tool"] == "fake_plc_write"
    assert row["undo_tool"] == "fake_plc_write"
    assert row["status"] == "recorded"
    assert row["note"] == "restore pre-write value"
    assert json.loads(row["undo_params"]) == {"value": 7, "target": "plant1"}
    assert json.loads(row["orig_params"])["value"] == 42


@pytest.mark.unit
def test_undo_returning_none_records_nothing(approver: None) -> None:
    fake_plc_write = _make_write(lambda params, result: None)

    result = fake_plc_write(42)

    assert "_undo_id" not in result, "undo=None means 'no safe inverse' — nothing recorded"
    assert get_undo_store().list() == []


@pytest.mark.unit
def test_broken_undo_callable_never_fails_the_write(approver: None) -> None:
    def _boom(params: dict[str, Any], result: Any) -> dict[str, Any]:
        raise RuntimeError("undo computation exploded")

    fake_plc_write = _make_write(_boom)

    result = fake_plc_write(42)  # must not raise

    assert result["applied"] == 42
    assert "_undo_id" not in result
    assert get_undo_store().list() == []


@pytest.mark.unit
def test_undo_row_survives_singleton_reset(approver: None) -> None:
    """Persistence, not memory: the row is readable through a fresh store."""
    fake_plc_write = _make_write(_inverse)
    undo_id = fake_plc_write(42)["_undo_id"]

    reset_undo_store()

    row = get_undo_store().get(undo_id)
    assert row is not None and row["undo_tool"] == "fake_plc_write"


@pytest.mark.unit
def test_store_rejects_descriptor_without_tool() -> None:
    undo_id = get_undo_store().record(
        skill="iaiops", tool="fake_plc_write", undo_descriptor={"params": {"value": 1}}
    )
    assert undo_id is None
    assert get_undo_store().list() == []


@pytest.mark.unit
def test_mark_and_list_by_status(approver: None) -> None:
    fake_plc_write = _make_write(_inverse)
    undo_id = fake_plc_write(42)["_undo_id"]
    store = get_undo_store()

    assert store.mark(undo_id, "applied") is True
    assert store.get(undo_id)["status"] == "applied"
    assert [r["undo_id"] for r in store.list(status="applied")] == [undo_id]
    assert store.list(status="recorded") == []
    assert store.mark("no-such-id", "applied") is False
