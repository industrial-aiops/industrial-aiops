"""`iaiops program doc` — a deterministic, self-contained program document (item B).

What it must be to be handed to a field engineer: the same bytes every time for
the same inputs (so two copies can be compared), zero network requests, every
string from the export escaped (a comment is whatever somebody typed), no LLM on
the path, and — when an endpoint is given — the exact-address cross-reference
with the same "never by name" rule as `xref-config`.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from test_plc_program import L5X_SAMPLE, SCL_SAMPLE
from test_program_field_xref import AWL_LINE
from typer.testing import CliRunner

from iaiops.core.brain.plc_program import program_doc
from iaiops.core.runtime.config import MonitorTag

HOSTILE_SCL = SCL_SAMPLE.replace("// start command", "// <script>alert(1)</script> start")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path / "iaiops-home"))
    return tmp_path


def _write(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _s7_target():
    return SimpleNamespace(
        name="line3",
        protocol="s7",
        plctype="Q",
        tags=(
            MonitorTag(ref="M10.0", label="running", role="run_state", running_when=(True,)),
            MonitorTag(ref="M99.0", label="Motor_Start"),
        ),
    )


@pytest.mark.unit
def test_doc_has_outline_variables_xref_and_honesty(home, tmp_path):
    html = program_doc.render(_write(tmp_path, "conveyor.scl", SCL_SAMPLE))
    for heading in ("Blocks", "Variables", "Cross-reference", "Call graph", "Change history"):
        assert heading in html
    assert "FB_Conveyor" in html and "FC_Scale" in html
    assert "RunTimer" in html and "TON" in html
    # Cross-reference rows cite real lines: `Running := TRUE;` is line 17.
    assert "<td>Running</td><td>write</td><td>FB_Conveyor</td><td>17</td>" in html
    assert "No LLM" in html


@pytest.mark.unit
def test_doc_is_deterministic(home, tmp_path):
    path = _write(tmp_path, "line3.L5X", L5X_SAMPLE)
    assert program_doc.render(path) == program_doc.render(path)


@pytest.mark.unit
def test_doc_is_self_contained_and_escaped(home, tmp_path):
    html = program_doc.render(_write(tmp_path, "conveyor.scl", HOSTILE_SCL))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert not re.search(r"(src|href)\s*=\s*[\"']?(https?:)?//", html)
    assert "<link" not in html and "@import" not in html
    assert "<script" not in html  # no script at all, not even an inert one


@pytest.mark.unit
def test_doc_change_history_absent_then_present(home, tmp_path):
    from iaiops.core.brain import program_baseline as pb

    path = _write(tmp_path, "conveyor.scl", SCL_SAMPLE)
    assert "No snapshot" in program_doc.render(path)
    pb.take_snapshot(path, label="approved v3.2")
    html = program_doc.render(path)
    assert "approved v3.2" in html and "identical" in html
    Path(path).write_text(SCL_SAMPLE.replace("T#2s", "T#5s") + "\n", encoding="utf-8")
    changed = program_doc.render(path)
    assert "logic_changed" in changed or "changed_outside_extracted_structure" in changed


@pytest.mark.unit
def test_doc_io_list_for_s7_absolute_operands(home, tmp_path):
    html = program_doc.render(_write(tmp_path, "ob1.awl", AWL_LINE))
    io = html.split("I/O list", 1)[1].split("</section>", 1)[0]
    for address in ("I0.0", "I0.1", "Q4.0"):
        assert address in io
    assert "MW20" not in io  # a marker is not I/O


@pytest.mark.unit
def test_doc_with_endpoint_carries_the_exact_match_xref(home, tmp_path):
    html = program_doc.render(_write(tmp_path, "ob1.awl", AWL_LINE), target=_s7_target())
    field = html.split("Field cross-reference", 1)[1]
    matched = field.split("Matched", 1)[1].split("</table>", 1)[0]
    assert "M10.0" in matched and "run_state" in matched
    # The label equal to a program symbol is not in the matched table.
    assert "Motor_Start" not in matched and "M99.0" not in matched


@pytest.mark.unit
def test_doc_with_unmatchable_endpoint_says_why_and_lists_nothing(home, tmp_path):
    target = SimpleNamespace(
        name="m1", protocol="modbus", plctype="Q", tags=(MonitorTag(ref="40001"),)
    )
    html = program_doc.render(_write(tmp_path, "ob1.awl", AWL_LINE), target=target)
    field = html.split("Field cross-reference", 1)[1]
    assert "Not comparable" in field and "Modbus" in field
    assert "Matched" not in field


@pytest.mark.unit
def test_cli_doc_writes_html_and_refuses_bad_out(home, tmp_path, monkeypatch):
    from iaiops.cli._root import app

    cfg = tmp_path / "cfg" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        yaml.safe_dump(
            {
                "targets": [
                    {
                        "name": "line3",
                        "protocol": "s7",
                        "host": "127.0.0.1",
                        "tags": [{"ref": "M10.0", "label": "running"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    path = _write(tmp_path, "ob1.awl", AWL_LINE)
    out = tmp_path / "docs" / "ob1.html"
    runner = CliRunner()
    result = runner.invoke(app, ["program", "doc", path, "--endpoint", "line3", "--out", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert "Field cross-reference" in text and "M10.0" in text
    bad = runner.invoke(app, ["program", "doc", path, "--out", str(tmp_path / "x.txt")])
    assert bad.exit_code == 1
    assert not (tmp_path / "x.txt").exists()


@pytest.mark.unit
def test_doc_path_imports_no_llm():
    import ast

    source = Path(program_doc.__file__).read_text(encoding="utf-8")
    names = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("llm" in name for name in names)


@pytest.mark.unit
def test_doc_empty_states_do_not_overclaim(home, tmp_path):
    awl = (
        "ORGANIZATION_BLOCK OB 1\nNETWORK\n"
        '      A     "Motor_Start"\n      L     DBW 4\nEND_ORGANIZATION_BLOCK\n'
    )
    target = SimpleNamespace(
        name="line3", protocol="s7", plctype="Q", tags=(MonitorTag(ref="DB102,S10.15"),)
    )
    html = program_doc.render(_write(tmp_path, "ob1.awl", awl), target=target)
    field = html.split("Field cross-reference", 1)[1]
    assert "Every address in the export is configured" not in field
    assert "Every configured point is named" not in field
    assert "Indirect access" in field
