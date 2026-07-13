"""Compliance report rendering tests (A3): golden substrings on the Markdown
for both 等保 levels, HTML rendering, and the governed MCP tool incl. the
inline-response bound."""

from __future__ import annotations

import pytest

from iaiops.core.brain.compliance import CONTROLS
from iaiops.core.brain.compliance_report import (
    DISCLAIMER,
    render_html_report,
    render_markdown_report,
)
from iaiops.core.governance.audit import reset_engine


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    reset_engine()
    yield
    reset_engine()


# ─── Markdown rendering ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_markdown_title_page_metadata():
    md = render_markdown_report(site="示例水厂", date="2026-07-02", version="9.9.9")
    assert "示例水厂" in md
    assert "2026-07-02" in md
    assert "9.9.9" in md
    # Honest wording: onboarding aid, not a certification — stated top AND bottom.
    assert md.count("非认证") >= 2
    assert "onboarding aid" in DISCLAIMER and DISCLAIMER in md


@pytest.mark.unit
@pytest.mark.parametrize(
    ("level", "expect", "absent"),
    [
        ("l2", "二级基线 (L2)", "三级增量 (L3 adds)"),
        ("三级", "三级增量 (L3 adds)", "二级基线 (L2)"),
    ],
)
def test_markdown_level_focus(level, expect, absent):
    md = render_markdown_report(level=level, date="2026-07-02")
    assert expect in md
    assert absent not in md


@pytest.mark.unit
def test_markdown_both_levels_and_crosswalk():
    md = render_markdown_report(date="2026-07-02")
    assert "二级基线 (L2)" in md and "三级增量 (L3 adds)" in md
    # IEC 62443 crosswalk table with FR clauses per pillar.
    assert "IEC 62443 FR1–FR6 跨框架对照" in md
    for fr in ("FR1", "FR2", "FR4", "FR5", "FR6"):
        assert fr in md
    # Every governance pillar shows up in the report.
    for control in CONTROLS:
        assert control["pillar"].split(" ")[0] in md


@pytest.mark.unit
def test_markdown_honest_gap_list_and_appendix():
    md = render_markdown_report(date="2026-07-02")
    assert "差距清单" in md
    # Real gaps from CONTROLS are reused, not re-invented.
    assert "待核实" in md
    assert "国产 OS" in md  # supply-chain gap text from CONTROLS
    # Governance appendix: hash chain, approval tokens, dry-run/undo, mTLS.
    for fact in (
        "审计哈希链",
        "prev_hash",
        "iaiops approve",
        "dry_run=True",
        "secrets.enc",
        "审批令牌",
    ):
        assert fact in md


@pytest.mark.unit
def test_markdown_rejects_unknown_level():
    with pytest.raises(ValueError, match="Unknown 等保 level"):
        render_markdown_report(level="l9", date="2026-07-02")


# ─── HTML rendering ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_html_report_is_standalone_page():
    html = render_html_report(site="示例<厂>", date="2026-07-02", level="l3")
    assert html.startswith("<!DOCTYPE html>")
    assert "<table>" in html and "<th>" in html and "</html>" in html
    # Site name is HTML-escaped, never injected raw.
    assert "示例&lt;厂&gt;" in html
    assert "示例<厂>" not in html
    assert "非认证" in html


# ─── Governed MCP tool ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_mcp_tools_are_governed():
    from mcp_server.tools.compliance_tools import (
        compliance_evidence_bundle,
        compliance_report,
    )

    for tool in (compliance_report, compliance_evidence_bundle):
        assert getattr(tool, "_is_governed_tool", False) is True
        assert getattr(tool, "_risk_level", "") == "low"


@pytest.mark.unit
def test_mcp_report_inline_within_bound():
    from mcp_server.tools.compliance_tools import compliance_report

    out = compliance_report(level="l3", site="testsite")
    assert "error" not in out
    assert out["line_count"] <= 400
    assert "truncated" not in out
    assert "testsite" in out["markdown"]


@pytest.mark.unit
def test_mcp_report_truncates_beyond_bound(monkeypatch):
    import mcp_server.tools.compliance_tools as mod

    monkeypatch.setattr(
        mod,
        "_render_markdown_report",
        lambda **_: "\n".join(f"line {i}" for i in range(1000)),
    )
    out = mod.compliance_report()
    assert out["truncated"] is True
    assert out["markdown"].count("\n") + 1 == 400
    assert "out_path" in out["hint"]


@pytest.mark.unit
def test_mcp_report_writes_out_path(tmp_path):
    from mcp_server.tools.compliance_tools import compliance_report

    target = tmp_path / "report.md"
    out = compliance_report(level="l2", site="mysite", out_path=str(target))
    assert out["path"] == str(target)
    assert "markdown" not in out
    content = target.read_text("utf-8")
    assert "mysite" in content and "非认证" in content


@pytest.mark.unit
def test_mcp_report_rejects_traversal_out_path(tmp_path):
    from mcp_server.tools.compliance_tools import compliance_report

    out = compliance_report(out_path=str(tmp_path / ".." / "evil.md"))
    assert "error" in out  # tool_errors converts the ValueError
