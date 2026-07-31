"""A failed call must not be audited as a successful one.

Tools do not raise. ``tool_errors`` sits INSIDE ``@governed_tool`` and converts
every exception into the canonical ``{error, hint}`` envelope, so the governance
wrapper saw a normal return value and recorded ``status='ok'``. Two consequences,
and the second is the one that bites:

* the audit trail — the product's compliance evidence — could not distinguish
  "wrote 5 to DB1" from "tried to write and the PLC was unreachable";
* ``_finalize`` reports ``success=(status == 'ok')`` to the pattern circuit
  breaker, so an armed pattern that failed every single time was reported as
  succeeding every single time. The breaker was blind to exactly the failures it
  exists to trip on.

The detection is deliberately narrow — see ``_returned_error``. These tests pin
both edges: the envelope IS recognised, and things that merely resemble it are not.
"""

from __future__ import annotations

import pytest

from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.decorators import governed_tool
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    reset_engine()
    reset_policy_engine()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")
    yield
    reset_engine()
    reset_policy_engine()


def _status(tool_name: str) -> str:
    rows = get_engine().query(tool=tool_name)
    assert rows, f"no audit row for {tool_name}"
    return rows[-1]["status"]


# ── the envelope is recognised ───────────────────────────────────────────────


@pytest.mark.unit
def test_returned_error_envelope_is_audited_as_an_error() -> None:
    @governed_tool(risk_level="low")
    def probe() -> dict:
        return {"error": "connection refused", "hint": "run iaiops doctor"}

    probe()
    assert _status("probe") == "error"


@pytest.mark.unit
def test_list_shaped_error_envelope_is_audited_as_an_error() -> None:
    """``tool_errors(shape="list")`` wraps the same envelope in a single-item list."""

    @governed_tool(risk_level="low")
    def probe() -> list:
        return [{"error": "connection refused", "hint": "run iaiops doctor"}]

    probe()
    assert _status("probe") == "error"


@pytest.mark.unit
def test_a_normal_result_is_still_audited_as_ok() -> None:
    @governed_tool(risk_level="low")
    def probe() -> dict:
        return {"value": 21.5}

    probe()
    assert _status("probe") == "ok"


# ── things that merely resemble it are not ───────────────────────────────────


@pytest.mark.unit
def test_an_error_count_of_zero_is_not_an_error() -> None:
    """A diagnostic tool reporting ``error`` as structured data is not failing."""

    @governed_tool(risk_level="low")
    def probe() -> dict:
        return {"error": None, "errors": [], "checked": 12}

    probe()
    assert _status("probe") == "ok"


@pytest.mark.unit
def test_a_structured_error_field_is_not_the_envelope() -> None:
    @governed_tool(risk_level="low")
    def probe() -> dict:
        return {"error": {"code": 7, "text": "bad address"}, "samples": 3}

    probe()
    assert _status("probe") == "ok"


@pytest.mark.unit
def test_a_multi_item_list_is_not_the_envelope() -> None:
    """A list of results that happens to include an error row is a partial success,
    not a failed call — the envelope shape is exactly one element."""

    @governed_tool(risk_level="low")
    def probe() -> list:
        return [{"ref": "a", "value": 1}, {"error": "unreadable", "hint": "check tag"}]

    probe()
    assert _status("probe") == "ok"


# ── consequences ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_a_failed_write_records_no_undo() -> None:
    """An inverse must correspond to a change that happened. The undo callables
    already gate on their own ``applied`` flag; this pins that a returned error
    never reaches them at all."""
    calls: list = []

    def _undo(params: dict, result) -> dict:
        calls.append((params, result))
        return {"tool": "probe", "params": {}}

    @governed_tool(risk_level="low", undo=_undo)
    def probe() -> dict:
        return {"error": "connection refused", "hint": "run iaiops doctor"}

    result = probe()
    assert calls == [], "undo computed for a call that changed nothing"
    assert "_undo_id" not in result


@pytest.mark.unit
def test_a_successful_write_still_records_its_undo() -> None:
    """Guards the fix above from over-reaching: real writes must keep their inverse."""

    @governed_tool(risk_level="low", undo=lambda params, result: {"tool": "probe", "params": {}})
    def probe() -> dict:
        return {"applied": True}

    assert "_undo_id" in probe()


@pytest.mark.unit
def test_the_circuit_breaker_is_told_the_call_failed(monkeypatch) -> None:
    """The reason this matters beyond the audit row: an armed pattern that fails
    every time was reported as succeeding every time, so its breaker never tripped."""
    from iaiops.core.governance import decorators as dec

    outcomes: list[bool] = []

    class _FakePattern:
        pattern_id = "p1"

    class _FakeMatch:
        armed = True
        pattern = _FakePattern()

    class _FakeEngine:
        """Stands in for the pattern engine on both sides of the call: it arms a
        match on the way in, and records what it was told on the way out."""

        def match(self, *, skill, tool, target):
            return _FakeMatch()

        def report_outcome(self, *, pattern_id, target, success):
            outcomes.append(success)

    monkeypatch.setattr(dec, "get_pattern_engine", lambda: _FakeEngine())

    @governed_tool(risk_level="low")
    def probe() -> dict:
        return {"error": "connection refused", "hint": "run iaiops doctor"}

    probe()

    assert outcomes == [False], f"circuit breaker told success={outcomes}"
