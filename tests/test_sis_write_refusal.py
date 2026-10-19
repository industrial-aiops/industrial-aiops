"""An endpoint marked ``safety: sis`` refuses every write — no approval unlocks it.

iaiops is not a safety system and is not an IEC 61508 / 61511 tool. A safety
instrumented system's setpoints are changed under the plant's own functional-
safety management of change, never through an agent's MCP call — so for an
endpoint the operator marks ``safety: sis`` the answer is not "ask more approvers"
(that is the enterprise approval policy's job for ordinary writes) but "no". Reads
stay allowed: looking at a SIS is how you troubleshoot around it.
"""

from __future__ import annotations

import pytest

from iaiops.core.governance import decorators as decorators_mod
from iaiops.core.governance.approvals import record_approval
from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.decorators import PolicyDenied, governed_tool
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine

pytestmark = pytest.mark.unit

CONFIG = """\
endpoints:
  - name: sis1
    protocol: modbus
    host: 10.0.0.9
    safety: sis
  - name: line1
    protocol: modbus
    host: 10.0.0.5
"""


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, "utf-8")
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    monkeypatch.setattr(decorators_mod, "_env_approver_warned", False)
    reset_engine()
    reset_policy_engine()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")
    yield
    reset_engine()
    reset_policy_engine()


def _write_tool():
    @governed_tool(risk_level="high", preview_param="dry_run")
    def write_setpoint(value: int, endpoint: str = "", dry_run: bool = True) -> dict:
        return {"written": value, "dry_run": dry_run}

    return write_setpoint


def _read_tool():
    @governed_tool(risk_level="low")
    def read_setpoint(endpoint: str = "") -> dict:
        return {"value": 1}

    return read_setpoint


def test_an_approved_write_to_a_sis_endpoint_is_refused():
    tool = _write_tool()
    record_approval("write_setpoint", "sis1", approved_by="alice", rationale="MOC-1")
    with pytest.raises(PolicyDenied) as exc:
        tool(5, endpoint="sis1", dry_run=False)
    assert "safety: sis" in exc.value.result.reason
    assert exc.value.result.rule == "safety_sis_no_writes"


def test_even_a_preview_write_to_a_sis_endpoint_is_refused():
    with pytest.raises(PolicyDenied):
        _write_tool()(5, endpoint="sis1", dry_run=True)


def test_the_refusal_is_audited_as_the_sis_rule():
    # Approved first: a denial for a MISSING approval would pass this test for the
    # wrong reason.
    record_approval("write_setpoint", "sis1", approved_by="alice", rationale="MOC-3")
    with pytest.raises(PolicyDenied):
        _write_tool()(5, endpoint="sis1", dry_run=False)
    rows = get_engine().query(tool="write_setpoint")
    assert rows and rows[0]["status"] == "denied"
    assert "safety_sis_no_writes" in str(rows[0].get("result", ""))


def test_reads_on_a_sis_endpoint_still_work():
    assert _read_tool()(endpoint="sis1") == {"value": 1}


def test_an_ordinary_endpoint_keeps_the_approval_flow():
    tool = _write_tool()
    record_approval("write_setpoint", "line1", approved_by="alice", rationale="MOC-2")
    assert tool(5, endpoint="line1", dry_run=False) == {"written": 5, "dry_run": False}


def test_an_unknown_safety_value_is_a_config_error(tmp_path, monkeypatch):
    from iaiops.core.runtime.config import load_config

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "endpoints:\n  - name: x\n    protocol: modbus\n    host: 10.0.0.1\n    safety: SIL3\n",
        "utf-8",
    )
    monkeypatch.setenv("IAIOPS_CONFIG", str(bad))
    # The VALUE is refused (not merely an unknown key — that would also say "safety").
    with pytest.raises(ValueError, match="safety must be"):
        load_config()


def test_safety_sis_is_a_known_key(tmp_path):
    from iaiops.core.runtime.config import load_config

    assert load_config().get_target("sis1").safety == "sis"
    assert load_config().get_target("line1").safety == ""
