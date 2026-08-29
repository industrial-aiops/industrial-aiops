"""There was no way to ask this tool what version it is.

Not `--version`, not a `version` subcommand, not `doctor`. Found by installing
0.24.0 from PyPI onto a lab box and typing the first thing anybody types:

    $ iaiops --version   -> No such option: --version
    $ iaiops version     -> No such command 'version'

For a product whose first iron rule is that the supported version of every
connector is a first-class fact, the opening question of every support
conversation was unanswerable from the tool. On an air-gapped plant network,
where most of these boxes live, you cannot go and look it up either.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import iaiops
from iaiops.cli._root import app

pytestmark = pytest.mark.unit

runner = CliRunner()


class TestTheToolCanSayWhatItIs:
    @pytest.mark.parametrize("flag", ["--version", "-V"])
    def test_the_flag_prints_the_version_and_exits_clean(self, flag):
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0, result.output
        assert iaiops.__version__ in result.output

    def test_it_reports_the_INSTALLED_version_not_a_literal(self, monkeypatch):
        """A hardcoded string is the same defect one release later.

        This repo already has `test_version_parity.py` because version strings
        drift wherever they are written down twice.
        """
        monkeypatch.setattr(iaiops, "__version__", "9.9.9-test")
        assert "9.9.9-test" in runner.invoke(app, ["--version"]).output

    def test_the_output_is_one_parseable_line(self):
        """Scripts and support tickets both read this; keep it boring."""
        lines = [ln for ln in runner.invoke(app, ["--version"]).output.splitlines() if ln.strip()]
        assert len(lines) == 1
        assert lines[0].split() == ["iaiops", iaiops.__version__]

    def test_the_root_callback_did_not_swallow_the_subcommands(self):
        """Adding a callback to a Typer app is a good way to break everything else."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for group in ("modbus", "readiness", "collect", "scan", "tags", "investigate"):
            assert group in result.output, f"{group} vanished from the root help"

    def test_bare_invocation_still_shows_help_rather_than_doing_nothing(self):
        assert runner.invoke(app, []).output.strip(), "no_args_is_help was lost"


class TestDoctorSaysItToo:
    def test_doctor_states_the_version_it_is_diagnosing(self, capsys):
        """`doctor` output is what a site pastes into a support thread.

        Without the version in it, the paste is missing the one fact that makes
        the rest of it interpretable.
        """
        from iaiops.doctor import run_doctor

        run_doctor(skip_probe=True)
        assert iaiops.__version__ in capsys.readouterr().out
