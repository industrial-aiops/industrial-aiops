"""Anything that REPORTS the config path must name the one it read.

`default_config_path()` resolves `$IAIOPS_CONFIG` for every loader — its own
docstring says why: two loaders meant two answers to "which file is this site
configured in", and pairing live evidence from one machine with history from
another is a wrong answer wearing the right shape.

The reporters had drifted back out of it. `iaiops doctor` printed "No config
file (~/.iaiops/config.yaml)" and then listed the endpoints it had just loaded
from the override; the compliance evidence bundle recorded the same default
path beside the targets it read from the other file. The doctor merely
contradicted itself in a support thread. The bundle is the artefact whose whole
job is not to.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.config import (
    CONFIG_ENV_VAR,
    CONFIG_FILE,
    config_path_source,
    default_config_path,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    """A real config at a path that is NOT the default."""
    path = tmp_path / "site.yaml"
    path.write_text(
        "endpoints:\n  - name: line1\n    protocol: modbus\n    host: 10.0.0.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    return path


class TestTheResolverItself:
    def test_the_override_wins(self, elsewhere):
        assert default_config_path() == elsewhere

    def test_the_source_is_reportable(self, elsewhere):
        assert config_path_source() == CONFIG_ENV_VAR

    def test_without_the_override_it_is_the_default(self, monkeypatch):
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        assert default_config_path() == CONFIG_FILE
        assert config_path_source() == "default"


class TestDoctorNamesTheFileItRead:
    def _run(self) -> str:
        from typer.testing import CliRunner

        from iaiops.cli._root import app

        return CliRunner().invoke(app, ["doctor", "--skip-probe"]).stdout

    def test_it_reports_the_override_not_the_default(self, elsewhere):
        out = self._run().replace("\n", "")
        assert "site.yaml" in out
        assert "No config file" not in out

    def test_it_says_where_the_path_came_from(self, elsewhere):
        """A bare non-default path leaves the reader unable to tell an override
        from a default, which is the question they are asking."""
        assert CONFIG_ENV_VAR in self._run().replace("\n", "")

    def test_the_default_case_is_unchanged(self, monkeypatch):
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        out = self._run().replace("\n", "")
        assert CONFIG_ENV_VAR not in out


class TestTheEvidenceBundleNamesTheFileItRead:
    """A bundle that cannot say which file it read is not evidence."""

    def test_the_recorded_path_is_the_one_loaded_from(self, elsewhere):
        from iaiops.core.governance.evidence import _doctor_summary

        summary = _doctor_summary()
        assert summary["config_file"] == str(elsewhere)
        assert summary["config_present"] is True

    def test_it_cannot_claim_absent_while_listing_targets(self, elsewhere):
        """The self-contradiction, asserted as one statement: these two fields
        came from different files, and that is how a bundle lies quietly."""
        from iaiops.core.governance.evidence import _doctor_summary

        summary = _doctor_summary()
        assert summary["targets"], "nothing was loaded, so the test proves nothing"
        assert summary["config_present"] is True

    def test_the_source_is_recorded(self, elsewhere):
        from iaiops.core.governance.evidence import _doctor_summary

        assert _doctor_summary()["config_path_source"] == CONFIG_ENV_VAR

    def test_the_default_case_records_the_default(self, monkeypatch):
        from iaiops.core.governance.evidence import _doctor_summary

        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        summary = _doctor_summary()
        assert summary["config_file"] == str(CONFIG_FILE)
        assert summary["config_path_source"] == "default"
