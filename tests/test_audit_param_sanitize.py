"""Audit param hygiene: control characters must never land in audit rows.

Param values can carry device/network-sourced text (node ids, error strings);
terminal escapes or C0/C1 control chars in them would flow untouched into the
audit DB and from there into SIEM forwards. The decorator must scrub string
values (recursively) before logging.
"""

from __future__ import annotations

import json

import pytest

from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.decorators import governed_tool
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    monkeypatch.delenv("OPCUA_AUDIT_RATIONALE", raising=False)
    reset_engine()
    reset_policy_engine()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")
    yield
    reset_engine()
    reset_policy_engine()


def _logged_params(tool_name: str) -> dict:
    rows = get_engine().query(tool=tool_name, status="ok")
    assert rows, f"no audit row for {tool_name}"
    return json.loads(rows[0]["params"])


@pytest.mark.unit
def test_control_chars_stripped_from_string_param_values():
    @governed_tool(risk_level="low")
    def annotate(note: str) -> dict:
        return {"ok": True}

    annotate("bad\x00\x1b[2Jvalue\x07")
    assert _logged_params("annotate")["note"] == "bad[2Jvalue"


@pytest.mark.unit
def test_control_chars_stripped_recursively_in_collections():
    @governed_tool(risk_level="low")
    def batch(meta: dict, items: list) -> dict:
        return {"ok": True}

    batch(meta={"inner": "a\x07b", "n": 3}, items=["x\x00y", 7])
    params = _logged_params("batch")
    assert params["meta"] == {"inner": "ab", "n": 3}
    assert params["items"] == ["xy", 7]


@pytest.mark.unit
def test_newlines_tabs_and_non_string_values_preserved():
    @governed_tool(risk_level="low")
    def write_note(text: str, value: float, flag: bool) -> dict:
        return {"ok": True}

    write_note("line1\nline2\tend", 42.5, True)
    params = _logged_params("write_note")
    assert params["text"] == "line1\nline2\tend"
    assert params["value"] == 42.5
    assert params["flag"] is True


@pytest.mark.unit
def test_sensitive_params_still_redacted_after_sanitize():
    @governed_tool(risk_level="low", sensitive_params=["password"])
    def connect(host: str, password: str) -> dict:
        return {"ok": True}

    connect("plc1\x1b]0;evil\x07", "s3cret")
    params = _logged_params("connect")
    assert params["password"] == "***"
    assert "\x1b" not in params["host"]
