"""`investigate --report` — the file that actually gets forwarded.

The renderer is tested in `test_investigation_report.py`. What is tested here is
the wiring, and one deliberate policy difference from `oee measure --report`.

`oee measure --report` REFUSES to write when the measurement was refused: an OEE
report is a number, so the file existing at all asserts one was measured. The
investigation report is the opposite — its content is how far this got and what
each step still needs, so the blocked case is the one most worth handing over. A
guard copied across from OEE would have deleted the product's most useful output
for exactly the sites that need it.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture
def cli():
    from iaiops.cli.investigate import investigate_app

    return investigate_app


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from iaiops.core.runtime import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".iaiops", raising=False)
    return tmp_path


class TestPlanWritesAReport:
    def test_a_file_is_written(self, cli, site, tmp_path):
        out = tmp_path / "r.html"
        result = runner.invoke(cli, ["plan", "--report", str(out)])
        assert result.exit_code == 0, result.output
        assert out.read_text("utf-8").startswith("<!doctype html>")

    def test_a_blocked_site_still_gets_a_file(self, cli, site, tmp_path):
        """The policy difference from OEE, and the whole reason this exists: an
        uninstrumented site is exactly who the report is for."""
        out = tmp_path / "r.html"
        assert runner.invoke(cli, ["plan", "--report", str(out)]).exit_code == 0
        assert "0 / 8" in out.read_text("utf-8") or "/ 8" in out.read_text("utf-8")

    def test_the_path_is_mentioned_so_the_operator_can_find_it(self, cli, site, tmp_path):
        out = tmp_path / "r.html"
        result = runner.invoke(cli, ["plan", "--report", str(out)])
        assert "r.html" in result.output

    def test_a_wrong_extension_is_refused_before_anything_is_written(self, cli, site, tmp_path):
        out = tmp_path / "r.exe"
        result = runner.invoke(cli, ["plan", "--report", str(out)])
        assert result.exit_code != 0
        assert not out.exists()

    def test_traversal_is_refused(self, cli, site, tmp_path):
        result = runner.invoke(cli, ["plan", "--report", str(tmp_path / ".." / "esc.html")])
        assert result.exit_code != 0

    def test_the_report_language_can_be_chosen(self, cli, site, tmp_path):
        out = tmp_path / "r.html"
        assert runner.invoke(cli, ["plan", "--report", str(out), "--lang", "zh"]).exit_code == 0
        assert 'lang="zh"' in out.read_text("utf-8")

    def test_an_unknown_language_is_refused(self, cli, site, tmp_path):
        out = tmp_path / "r.html"
        result = runner.invoke(cli, ["plan", "--report", str(out), "--lang", "fr"])
        assert result.exit_code != 0


class TestOpenAndShowWriteAReport:
    def _open(self, cli, out=None):
        args = [
            "open",
            "line1",
            "--start",
            "2026-08-26T10:00:00Z",
            "--end",
            "2026-08-26T10:10:00Z",
        ]
        if out is not None:
            args += ["--report", str(out)]
        return runner.invoke(cli, args)

    def test_open_writes_one(self, cli, site, tmp_path):
        out = tmp_path / "inv.html"
        assert self._open(cli, out).exit_code == 0, self._open(cli, out).output
        assert out.read_text("utf-8").startswith("<!doctype html>")

    def test_show_writes_one_for_a_saved_investigation(self, cli, site, tmp_path):
        import json

        opened = runner.invoke(
            cli,
            [
                "open",
                "line1",
                "--start",
                "2026-08-26T10:00:00Z",
                "--end",
                "2026-08-26T10:10:00Z",
                "--json",
            ],
        )
        inv_id = json.loads(opened.output)["id"]
        out = tmp_path / "again.html"
        assert runner.invoke(cli, ["show", inv_id, "--report", str(out)]).exit_code == 0
        assert inv_id in out.read_text("utf-8")

    def test_without_the_flag_no_file_appears(self, cli, site, tmp_path):
        """The report is opt-in. A command that wrote files nobody asked for would
        leave evidence artifacts scattered around a plant laptop."""
        before = set(tmp_path.iterdir())
        self._open(cli)
        assert {p for p in tmp_path.iterdir() if p.suffix == ".html"} == {
            p for p in before if p.suffix == ".html"
        }
