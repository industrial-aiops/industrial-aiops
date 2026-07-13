"""change_limits enforcement: numeric write bounds deny out-of-range calls,
and unenforceable rule shapes fail closed at config load (never warn-and-allow).
"""

from __future__ import annotations

import json
import os

import pytest

from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.policy import PolicyEngine

LIMIT_RULES = """\
change_limits:
  - name: setpoint_cap
    operations: ["write_setpoint*"]
    param: value
    min: 0
    max: 100
    reason: Setpoint must stay within 0-100.
"""


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    reset_engine()
    yield
    reset_engine()


def _engine(tmp_path, text: str = LIMIT_RULES) -> PolicyEngine:
    rules = tmp_path / "rules.yaml"
    rules.write_text(text, "utf-8")
    return PolicyEngine(rules)


def _bump_mtime(path) -> None:
    stat = path.stat()
    os.utime(path, (stat.st_atime + 10, stat.st_mtime + 10))


# ── enforcement of well-formed rules ──────────────────────────────────


@pytest.mark.unit
def test_within_limit_allowed(tmp_path):
    assert _engine(tmp_path).check_allowed("write_setpoint", params={"value": 50}).allowed


@pytest.mark.unit
def test_exceeding_max_denied(tmp_path):
    result = _engine(tmp_path).check_allowed("write_setpoint", params={"value": 150})
    assert not result.allowed
    assert result.rule == "setpoint_cap"
    assert "100" in result.reason


@pytest.mark.unit
def test_below_min_denied(tmp_path):
    result = _engine(tmp_path).check_allowed("write_setpoint", params={"value": -5})
    assert not result.allowed


@pytest.mark.unit
def test_boundary_values_allowed(tmp_path):
    engine = _engine(tmp_path)
    assert engine.check_allowed("write_setpoint", params={"value": 0}).allowed
    assert engine.check_allowed("write_setpoint", params={"value": 100}).allowed


@pytest.mark.unit
def test_numeric_string_value_enforced(tmp_path):
    result = _engine(tmp_path).check_allowed("write_setpoint", params={"value": "150"})
    assert not result.allowed


@pytest.mark.unit
def test_non_numeric_value_fails_closed(tmp_path):
    result = _engine(tmp_path).check_allowed("write_setpoint", params={"value": "ramp"})
    assert not result.allowed
    assert "numeric" in result.reason


@pytest.mark.unit
def test_bool_value_fails_closed(tmp_path):
    result = _engine(tmp_path).check_allowed("write_setpoint", params={"value": True})
    assert not result.allowed


@pytest.mark.unit
def test_nan_value_fails_closed(tmp_path):
    result = _engine(tmp_path).check_allowed("write_setpoint", params={"value": "nan"})
    assert not result.allowed


@pytest.mark.unit
def test_other_operations_unaffected(tmp_path):
    assert _engine(tmp_path).check_allowed("read_tag", params={"value": 999}).allowed


@pytest.mark.unit
def test_missing_param_does_not_constrain_call(tmp_path):
    assert _engine(tmp_path).check_allowed("write_setpoint", params={"node": "x"}).allowed


# ── unenforceable shapes fail closed at load ──────────────────────────


@pytest.mark.unit
def test_malformed_limits_retain_last_known_good_rules(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(LIMIT_RULES, "utf-8")
    engine = PolicyEngine(rules)
    assert not engine.check_allowed("write_setpoint", params={"value": 150}).allowed

    # A rule with no enforceable bound must fail the load — the previous
    # (enforcing) rule set is retained, not degraded to allow-all.
    rules.write_text("change_limits:\n  - name: broken\n    operations: ['write_*']\n", "utf-8")
    _bump_mtime(rules)
    assert not engine.check_allowed("write_setpoint", params={"value": 150}).allowed


@pytest.mark.unit
def test_legacy_dict_shape_rejected_and_audited_at_load(tmp_path):
    audit = get_engine(tmp_path / "audit.db")
    rules = tmp_path / "rules.yaml"
    rules.write_text("change_limits:\n  max_cpu_percent: 20\n", "utf-8")
    PolicyEngine(rules)

    rows = audit.query(status="policy_load_failed")
    assert rows, "unenforceable change_limits must be audited as a load failure"
    assert "change_limits" in json.dumps(rows[0])


@pytest.mark.unit
def test_non_numeric_bound_rejected_at_load(tmp_path):
    audit = get_engine(tmp_path / "audit.db")
    rules = tmp_path / "rules.yaml"
    rules.write_text("change_limits:\n  - param: value\n    max: lots\n", "utf-8")
    PolicyEngine(rules)
    assert audit.query(status="policy_load_failed")
