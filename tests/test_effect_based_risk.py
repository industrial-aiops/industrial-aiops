"""Effect-based risk in ``@governed_tool`` (``preview_param``): a preview/dry-run
call changes no state, so it audits and gates at ``low`` (no approver) even on a
``high`` tool, while the real write keeps the declared ``high``.

Used by both front-ends: the MCP write tools opt in with ``preview_param="dry_run"``
(preview = ``dry_run`` truthy) and the CLI write commands with
``preview_param="apply", preview_truthy=False`` (preview = ``apply`` falsy). The
parameter defaults off, so tools that do not opt in — and the sibling
iaiops-energy / iaiops-enterprise repos sharing this decorator — are unchanged.
"""

from __future__ import annotations

import pytest

from iaiops.core.governance.audit import get_engine
from iaiops.core.governance.decorators import PolicyDenied, governed_tool


def _last_risk(tool: str) -> str:
    """Risk level of the most recent audit row for ``tool`` (query is newest-first)."""
    return get_engine().query(tool=tool)[0]["risk_level"]


@pytest.mark.unit
def test_dry_run_preview_audits_low_and_is_not_gated():
    """A ``high`` tool called as a preview audits at ``low`` and needs no approver."""

    @governed_tool(risk_level="high", preview_param="dry_run")
    def write_thing(value: int, dry_run: bool = True) -> dict:
        return {"value": value, "dry_run": dry_run}

    # Default dry_run=True → preview → low → runs without an approver.
    assert write_thing(value=1) == {"value": 1, "dry_run": True}
    assert _last_risk("write_thing") == "low"


@pytest.mark.unit
def test_real_write_keeps_declared_high_and_is_gated():
    """The same tool with ``dry_run=False`` is ``high`` — denied without an approver."""

    @governed_tool(risk_level="high", preview_param="dry_run")
    def write_thing2(value: int, dry_run: bool = True) -> dict:
        return {"value": value}

    with pytest.raises(PolicyDenied):
        write_thing2(value=1, dry_run=False)
    assert _last_risk("write_thing2") == "high"


@pytest.mark.unit
def test_inverted_flag_for_the_cli_apply_convention():
    """``preview_truthy=False`` inverts the polarity for the CLI's ``apply`` flag:
    a preview is ``apply=False``, the real write is ``apply=True``."""

    @governed_tool(risk_level="high", preview_param="apply", preview_truthy=False)
    def cli_write(value: int, apply: bool = False) -> dict:
        return {"value": value}

    assert cli_write(value=1) == {"value": 1}  # apply=False → preview → low
    assert _last_risk("cli_write") == "low"
    with pytest.raises(PolicyDenied):
        cli_write(value=1, apply=True)  # real write → high → gated
    assert _last_risk("cli_write") == "high"


@pytest.mark.unit
def test_no_preview_param_preserves_declared_risk():
    """Without ``preview_param`` the declared risk always applies — the default
    that keeps sibling repos / non-opted-in tools behaving exactly as before."""

    @governed_tool(risk_level="high")
    def always_high(value: int, dry_run: bool = True) -> dict:
        return {"value": value}

    with pytest.raises(PolicyDenied):
        always_high(value=1, dry_run=True)  # still high despite dry_run=True
    assert _last_risk("always_high") == "high"


@pytest.mark.unit
def test_declared_risk_metadata_stays_high_for_classification():
    """The wrapper's ``_risk_level`` remains the DECLARED risk (high) so registry
    classification is unaffected; only the per-call audit reflects the effect."""

    @governed_tool(risk_level="high", preview_param="dry_run")
    def marked(value: int, dry_run: bool = True) -> dict:
        return {}

    assert marked._risk_level == "high"
    assert marked._preview_param == "dry_run"
