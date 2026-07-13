"""Tests for the L5 auto-remediation pattern engine (``governance/patterns.py``).

Covers the arming preconditions (signed + approved + low/reversible/repeatable),
the per-target rate limits, the consecutive-failure circuit breaker, and the
end-to-end ``@governed_tool`` integration (result annotation + breaker opening
after real failures).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from iaiops.core.governance.decorators import governed_tool
from iaiops.core.governance.patterns import get_pattern_engine

PATTERN_ID = "restart-collector-agent"
SKILL = "iaiops"
TOOL = "restart_agent"


def _write_pattern(home: Path, **overrides: Any) -> None:
    """Write a fully armable pattern YAML into the isolated IAIOPS_HOME."""
    doc: dict[str, Any] = {
        "schema_version": 1,
        "pattern_id": PATTERN_ID,
        "classification": {"risk": "low", "reversible": True, "repeatable": True},
        "action": {"skill": SKILL, "tool": TOOL},
        "approval": {"status": "approved", "signed_by": "alice"},
        "rate_limit": {"max_per_hour": 100, "max_per_day": 200},
        "circuit_breaker": {"consecutive_validation_failures": 2, "disable_seconds": 3600},
    }
    doc.update(overrides)
    patterns_dir = home / "auto-remediation-patterns"
    patterns_dir.mkdir(parents=True, exist_ok=True)
    (patterns_dir / f"{doc['pattern_id']}.yaml").write_text(yaml.safe_dump(doc), "utf-8")


@pytest.mark.unit
def test_signed_approved_low_risk_pattern_arms(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home)
    match = get_pattern_engine().match(skill=SKILL, tool=TOOL, target="edge1")
    assert match is not None
    assert match.armed is True
    assert match.pattern.pattern_id == PATTERN_ID


@pytest.mark.unit
def test_non_matching_tool_returns_none(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home)
    assert get_pattern_engine().match(skill=SKILL, tool="other_tool", target="edge1") is None


@pytest.mark.unit
def test_unsigned_pattern_is_not_armable(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home, approval={"status": "approved", "signed_by": ""})
    match = get_pattern_engine().match(skill=SKILL, tool=TOOL, target="edge1")
    assert match is not None
    assert match.armed is False
    assert "not armable" in match.reason


@pytest.mark.unit
def test_expired_pattern_is_not_armable(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home, expires_at="2000-01-01T00:00:00Z")
    match = get_pattern_engine().match(skill=SKILL, tool=TOOL, target="edge1")
    assert match is not None
    assert match.armed is False


@pytest.mark.unit
def test_hourly_rate_limit_blocks_further_arming(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home, rate_limit={"max_per_hour": 2, "max_per_day": 200})
    engine = get_pattern_engine()

    for _ in range(2):
        assert engine.match(skill=SKILL, tool=TOOL, target="edge1").armed is True
    third = engine.match(skill=SKILL, tool=TOOL, target="edge1")
    assert third.armed is False
    assert "hourly cap" in third.reason
    # Rate limits are per target — a different target still arms.
    assert engine.match(skill=SKILL, tool=TOOL, target="edge2").armed is True


@pytest.mark.unit
def test_circuit_breaker_opens_after_consecutive_failures(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home)  # threshold=2, disable=3600s
    engine = get_pattern_engine()
    assert engine.match(skill=SKILL, tool=TOOL, target="edge1").armed is True

    engine.report_outcome(pattern_id=PATTERN_ID, target="edge1", success=False)
    engine.report_outcome(pattern_id=PATTERN_ID, target="edge1", success=False)

    tripped = engine.match(skill=SKILL, tool=TOOL, target="edge1")
    assert tripped.armed is False
    assert "circuit-broken" in tripped.reason
    # Breaker state is per target — other targets are unaffected.
    assert engine.match(skill=SKILL, tool=TOOL, target="edge2").armed is True


@pytest.mark.unit
def test_success_resets_the_failure_counter(isolated_iaiops_home: Path) -> None:
    _write_pattern(isolated_iaiops_home)  # threshold=2
    engine = get_pattern_engine()

    engine.report_outcome(pattern_id=PATTERN_ID, target="edge1", success=False)
    engine.report_outcome(pattern_id=PATTERN_ID, target="edge1", success=True)
    engine.report_outcome(pattern_id=PATTERN_ID, target="edge1", success=False)

    # Never 2 consecutive failures — the breaker must still be closed.
    assert engine.match(skill=SKILL, tool=TOOL, target="edge1").armed is True


@pytest.mark.unit
def test_governed_tool_annotates_result_and_breaker_degrades_end_to_end(
    isolated_iaiops_home: Path,
) -> None:
    """Full path: armed pattern annotates results; real failures open the breaker."""
    _write_pattern(isolated_iaiops_home)  # threshold=2
    behavior = {"fail": False}

    def restart_agent(target: str = "edge1") -> dict[str, Any]:
        if behavior["fail"]:
            raise RuntimeError("collector restart failed")
        return {"restarted": True}

    # The decorator infers skill from __module__ and tool from __name__; make
    # the fake tool report as (iaiops, restart_agent) to match action.{skill,tool}.
    restart_agent.__module__ = "iaiops.core.testing_fake"
    restart_agent = governed_tool(risk_level="low")(restart_agent)

    armed_result = restart_agent(target="edge1")
    assert armed_result["_pattern_id"] == PATTERN_ID
    assert armed_result["_pattern_armed"] is True

    behavior["fail"] = True
    for _ in range(2):
        with pytest.raises(RuntimeError):
            restart_agent(target="edge1")

    behavior["fail"] = False
    degraded = restart_agent(target="edge1")
    assert degraded["restarted"] is True, "breaker degrades arming, never blocks the call"
    assert "_pattern_armed" not in degraded, "circuit-broken pattern must not arm"
