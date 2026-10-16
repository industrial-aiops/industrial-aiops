"""The NIS2 / CRA self-assessment, rendered — and the 等保 report left as it was.

Selection is a ``framework`` argument on the existing report function, MCP tool
and CLI (no new tool: the tool count is a README fact). The default stays the
等保 2.0 / IEC 62443 report byte-for-byte in substance; the EU report is
English, because its reader is an EU assessor.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from iaiops.core.brain.compliance_eu import CRA_ITEMS, EU_DISCLAIMER, NIS2_ITEMS
from iaiops.core.brain.compliance_report import render_html_report, render_markdown_report
from iaiops.core.governance.audit import reset_engine

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    reset_engine()
    yield
    reset_engine()


@pytest.mark.parametrize(("framework", "items"), [("nis2", NIS2_ITEMS), ("cra", CRA_ITEMS)])
def test_eu_report_lists_every_item_and_both_disclaimers(framework, items):
    md = render_markdown_report(framework=framework, site="Plant A", date="2026-10-15")
    for item in items:
        assert item["ref"] in md, item["ref"]
    assert md.count(EU_DISCLAIMER) == 2  # top and bottom, like the 等保 report
    assert "Plant A" in md and "2026-10-15" in md
    assert "等保" not in md  # the EU reader gets the EU report only


def test_eu_report_separates_organisational_from_product_evidence():
    md = render_markdown_report(framework="nis2", date="2026-10-15")
    assert "Organisational measures" in md
    org = md.split("Organisational measures", 1)[1]
    for item in NIS2_ITEMS:
        if item["coverage"] == "organisational":
            assert item["ref"] in org


def test_eu_report_appendix_cites_mechanisms_with_code_anchors():
    md = render_markdown_report(framework="cra", date="2026-10-15")
    assert "Appendix" in md
    assert "AuditEngine.verify_chain" in md


def test_eu_both_renders_nis2_and_cra():
    md = render_markdown_report(framework="eu", date="2026-10-15")
    assert NIS2_ITEMS[0]["ref"] in md and CRA_ITEMS[-1]["ref"] in md


def test_default_report_is_still_the_dengbao_report():
    md = render_markdown_report(date="2026-10-15")
    assert "等保 2.0" in md and "IEC 62443 FR1–FR6" in md
    assert "NIS2 Art. 21(2)" not in md
    # The title page lists only the frameworks this report actually renders.
    header = md.split("## 1.", 1)[0]
    assert "NIS2" not in header and "CRA" not in header


def test_level_is_refused_on_an_eu_report():
    """等保 levels mean nothing under NIS2; silently ignoring the flag would mislead."""
    with pytest.raises(ValueError, match="等保"):
        render_markdown_report(framework="nis2", level="l3", date="2026-10-15")


def test_unknown_framework_is_refused():
    with pytest.raises(ValueError, match="nis2"):
        render_markdown_report(framework="gdpr", date="2026-10-15")


def test_eu_html_is_english_and_escaped():
    html = render_html_report(framework="cra", site="Plant <B>", date="2026-10-15")
    assert '<html lang="en">' in html
    assert "Plant &lt;B&gt;" in html and "Plant <B>" not in html
    assert "<title>iaiops cybersecurity self-assessment — Plant &lt;B&gt;</title>" in html


# ─── MCP + CLI fronts ────────────────────────────────────────────────────────


def test_mcp_report_framework_parameter():
    from mcp_server.tools.compliance_tools import compliance_report

    out = compliance_report(framework="nis2", site="Plant A")
    assert "error" not in out, out
    assert out["framework"] == "nis2"
    assert "NIS2 Art. 21(2)(j)" in out["markdown"]


def test_mcp_report_refuses_level_with_eu_framework():
    from mcp_server.tools.compliance_tools import compliance_report

    out = compliance_report(framework="cra", level="三级")
    assert "error" in out


def test_mcp_frameworks_framework_parameter():
    from mcp_server.tools.compliance_tools import compliance_frameworks

    out = compliance_frameworks(framework="cra")
    assert "error" not in out, out
    assert out["item_count"] == len(CRA_ITEMS)
    assert "crosswalk" in compliance_frameworks()


def test_cli_prints_a_framework_table():
    from iaiops.cli._root import app

    result = CliRunner().invoke(app, ["compliance", "--framework", "nis2"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["framework"]["id"] == "nis2"


def test_cli_renders_an_eu_report(tmp_path):
    from iaiops.cli._root import app

    out = tmp_path / "cra.md"
    result = CliRunner().invoke(
        app, ["compliance", "report", "--framework", "cra", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "CRA Annex I Part II(8)" in out.read_text("utf-8")


def test_eu_report_shows_what_iaiops_does_on_each_row():
    md = render_markdown_report(framework="cra", date="2026-10-15")
    item = next(i for i in CRA_ITEMS if i["ref"].endswith("Part I(2)(l)"))
    assert item["iaiops"].split(" — ")[0] in md


def test_eu_report_counts_partial_evidence_separately():
    md = render_markdown_report(framework="cra", date="2026-10-15")
    assert "partial_evidence" in md.split("### 1.1", 1)[0]


@pytest.mark.parametrize("word", ["compliant", "certified", "satisfies", "meets the", "fully"])
def test_rendered_eu_report_never_flatters(word):
    md = render_markdown_report(framework="eu", date="2026-10-15").lower()
    assert word not in md


def test_mcp_report_echoes_the_normalised_framework():
    from mcp_server.tools.compliance_tools import compliance_report

    assert compliance_report(framework=" Nis2 ")["framework"] == "nis2"
    assert compliance_report()["framework"] == "dengbao"
    out = compliance_report(framework="gxp")
    assert "error" in out


def test_cli_refuses_framework_with_another_table_flag():
    from iaiops.cli._root import app

    result = CliRunner().invoke(app, ["compliance", "--framework", "nis2", "--frameworks"])
    assert result.exit_code != 0
