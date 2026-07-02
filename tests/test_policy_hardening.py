"""Policy-engine hardening tests: builtin approver default (H-1), fail-closed
rule loading (H-2), and the scoped kill switch (M-1)."""

from __future__ import annotations

import os

import pytest

from iaiops.core.governance import policy as policy_mod
from iaiops.core.governance.audit import AuditEngine, reset_engine
from iaiops.core.governance.policy import PolicyEngine

RULES = """\
deny:
  - name: no_deletes
    operations: ["delete_*"]
    reason: deletes forbidden
risk_tiers:
  - name: prod_writes_dual
    operations: ["write_*"]
    tier: dual
"""


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Isolate governance state and reset per-process warning flags."""
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("IAIOPS_POLICY_DISABLED", raising=False)
    monkeypatch.delenv("OPCUA_POLICY_DISABLED", raising=False)
    monkeypatch.setattr(policy_mod, "_legacy_disable_warned", False)
    reset_engine()
    yield
    reset_engine()


def _bump_mtime(path) -> None:
    stat = path.stat()
    os.utime(path, (stat.st_atime + 10, stat.st_mtime + 10))


# ── H-1: builtin safe default tier ────────────────────────────────────


@pytest.mark.unit
def test_no_rules_high_risk_requires_approver(tmp_path):
    engine = PolicyEngine(tmp_path / "missing.yaml")
    decision = engine.required_approval_tier("write_coil", risk_level="high")
    assert decision.tier == "dual"
    assert decision.rule == "builtin_default"
    assert decision.requires_approver


@pytest.mark.unit
def test_no_rules_critical_risk_requires_approver(tmp_path):
    engine = PolicyEngine(tmp_path / "missing.yaml")
    decision = engine.required_approval_tier("delete_all", risk_level="critical")
    assert decision.requires_approver


@pytest.mark.unit
def test_no_rules_low_risk_stays_ungated(tmp_path):
    engine = PolicyEngine(tmp_path / "missing.yaml")
    for level in ("low", "medium"):
        decision = engine.required_approval_tier("read_tag", risk_level=level)
        assert decision.tier == "none"
        assert not decision.requires_approver


@pytest.mark.unit
def test_explicit_risk_tiers_override_builtin_default(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, "utf-8")
    engine = PolicyEngine(rules)
    # Operator declared tiers: an op no tier matches stays ungated even at high risk.
    decision = engine.required_approval_tier("reboot_plc", risk_level="high")
    assert decision.tier == "none"
    assert decision.rule == "no_tier_match"
    # …and the declared rule still gates its operations.
    assert engine.required_approval_tier("write_coil", risk_level="low").tier == "dual"


@pytest.mark.unit
def test_dead_confirmation_helper_removed():
    assert not hasattr(policy_mod, "risk_requires_confirmation")


# ── H-2: fail-closed rule loading ─────────────────────────────────────


@pytest.mark.unit
def test_parse_failure_retains_previous_rules(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, "utf-8")
    engine = PolicyEngine(rules)
    assert not engine.check_allowed("delete_segment").allowed

    rules.write_text("deny: [unclosed\n", "utf-8")
    _bump_mtime(rules)
    # Last-known-good rules stay enforced — no allow-all degrade.
    assert not engine.check_allowed("delete_segment").allowed
    assert engine.required_approval_tier("write_coil", risk_level="low").tier == "dual"


@pytest.mark.unit
def test_deletion_retains_last_known_good_rules(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, "utf-8")
    engine = PolicyEngine(rules)
    assert not engine.check_allowed("delete_segment").allowed

    rules.unlink()
    assert not engine.check_allowed("delete_segment").allowed


@pytest.mark.unit
def test_recovery_after_parse_failure(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, "utf-8")
    engine = PolicyEngine(rules)

    rules.write_text("deny: [unclosed\n", "utf-8")
    _bump_mtime(rules)
    assert not engine.check_allowed("delete_segment").allowed

    rules.write_text("deny: []\n", "utf-8")
    _bump_mtime(rules)
    _bump_mtime(rules)
    assert engine.check_allowed("delete_segment").allowed


@pytest.mark.unit
def test_parse_failure_writes_audit_row(tmp_path):
    from iaiops.core.governance.audit import get_engine

    reset_engine()
    audit = get_engine(tmp_path / "audit.db")
    assert isinstance(audit, AuditEngine)

    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, "utf-8")
    engine = PolicyEngine(rules)
    rules.write_text("deny: [unclosed\n", "utf-8")
    _bump_mtime(rules)
    engine.check_allowed("read_tag")  # triggers hot-reload attempt

    rows = audit.query(status="policy_load_failed")
    assert rows and rows[0]["tool"] == "policy_engine"


# ── M-1: scoped kill switch ───────────────────────────────────────────


@pytest.mark.unit
def test_bypass_applies_to_low_risk_only(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, "utf-8")
    engine = PolicyEngine(rules)
    monkeypatch.setenv("IAIOPS_POLICY_DISABLED", "1")

    low = engine.check_allowed("delete_segment", risk_level="low")
    assert low.allowed and low.rule == "policy_disabled"

    for level in ("high", "critical"):
        result = engine.check_allowed("delete_segment", risk_level=level)
        assert not result.allowed, f"kill switch must not bypass {level} risk"


@pytest.mark.unit
def test_bypass_does_not_relax_approver_tier(tmp_path, monkeypatch):
    engine = PolicyEngine(tmp_path / "missing.yaml")
    monkeypatch.setenv("IAIOPS_POLICY_DISABLED", "1")
    decision = engine.required_approval_tier("write_coil", risk_level="high")
    assert decision.requires_approver


@pytest.mark.unit
def test_legacy_env_var_still_works_with_deprecation(tmp_path, monkeypatch, caplog):
    engine = PolicyEngine(tmp_path / "missing.yaml")
    monkeypatch.setenv("OPCUA_POLICY_DISABLED", "1")
    with caplog.at_level("WARNING", logger="iaiops.policy"):
        result = engine.check_allowed("read_tag", risk_level="low")
    assert result.allowed and result.rule == "policy_disabled"
    assert any("deprecated" in rec.message for rec in caplog.records)


# ── iaiops init: default rules.yaml ───────────────────────────────────


@pytest.mark.unit
def test_init_writes_default_rules_with_risk_tiers(tmp_path):
    import yaml

    from iaiops.cli.init import _write_default_rules

    _write_default_rules()
    rules_file = tmp_path / "rules.yaml"
    assert rules_file.exists()
    rules = yaml.safe_load(rules_file.read_text("utf-8"))
    tiers = rules["risk_tiers"]
    assert any(
        t.get("min_risk_level") == "high" and t.get("tier") in ("dual", "review")
        for t in tiers
    )
    # The written defaults must gate high-risk ops when loaded.
    engine = PolicyEngine(rules_file)
    assert engine.required_approval_tier("anything", risk_level="high").requires_approver


@pytest.mark.unit
def test_init_never_overwrites_existing_rules(tmp_path):
    from iaiops.cli.init import _write_default_rules

    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text("deny: []\n", "utf-8")
    _write_default_rules()
    assert rules_file.read_text("utf-8") == "deny: []\n"
