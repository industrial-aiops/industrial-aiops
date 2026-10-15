"""`iaiops init` must write the file every other command reads — and only its endpoints.

Two defects shared one cause: the wizard kept its own idea of the config file.

- It wrote ``CONFIG_FILE`` (bound at import) while every loader resolves
  ``$IAIOPS_CONFIG`` through ``default_config_path()``. With the override set,
  ``init`` reported success and the endpoint landed in a file no command reads.
- It rewrote the file as ``{"endpoints": [...]}``, so adding one endpoint
  deleted the ``historian:`` section — override or not.

The import-time copy also meant ``init`` ignored the test-isolation fixture,
which moves the config root by patching the module: a test driving the wizard
without the override would have written into the developer's real ~/.iaiops.
"""

from __future__ import annotations

import stat

import pytest
import yaml
from typer.testing import CliRunner

from iaiops.core.runtime import config as _config_mod
from iaiops.core.runtime.config import CONFIG_ENV_VAR, load_config

pytestmark = pytest.mark.unit

_HISTORIAN = {"historian": {"reader": "tdengine", "host": "10.0.0.20", "database": "plant"}}

# name, protocol, modbus host, port, unit id, "add another?", "run doctor?"
_ADD_PRESS2 = "press2\nmodbus\n10.0.0.9\n502\n1\nn\nn\n"


def _run_init() -> str:
    from iaiops.cli._root import app

    result = CliRunner().invoke(app, ["init"], input=_ADD_PRESS2)
    assert result.exit_code == 0, result.output
    return result.output


def _existing_site(path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "endpoints": [{"name": "line1", "protocol": "modbus", "host": "10.0.0.5"}],
                **_HISTORIAN,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _master_password(monkeypatch):
    monkeypatch.setenv("IAIOPS_MASTER_PASSWORD", "test-only-master")


@pytest.fixture
def override(tmp_path, monkeypatch):
    path = tmp_path / "sites" / "plant-b.yaml"
    path.parent.mkdir()
    _existing_site(path)
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    return path


class TestFollowsTheOverride:
    def test_the_endpoint_lands_in_the_file_commands_read(self, override):
        _run_init()
        names = [t.name for t in load_config().targets]
        assert names == ["line1", "press2"]

    def test_the_default_file_is_not_touched(self, override):
        _run_init()
        assert not _config_mod.CONFIG_FILE.exists()

    def test_it_says_which_file_and_why(self, override):
        out = _run_init().replace("\n", "")
        assert str(override.name) in out
        assert f"via ${CONFIG_ENV_VAR}" in out

    def test_it_does_not_chmod_a_directory_it_does_not_own(self, override):
        parent = override.parent
        parent.chmod(0o755)
        _run_init()
        assert stat.S_IMODE(parent.stat().st_mode) == 0o755


class TestKeepsWhatItDidNotWrite:
    def test_historian_survives_with_the_override(self, override):
        _run_init()
        raw = yaml.safe_load(override.read_text("utf-8"))
        assert raw["historian"] == _HISTORIAN["historian"]

    def test_historian_survives_in_the_default_file(self, monkeypatch):
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        default = _config_mod.CONFIG_FILE
        default.parent.mkdir(parents=True, exist_ok=True)
        _existing_site(default)
        _run_init()
        raw = yaml.safe_load(default.read_text("utf-8"))
        assert raw["historian"] == _HISTORIAN["historian"]
        assert [e["name"] for e in raw["endpoints"]] == ["line1", "press2"]

    def test_a_legacy_targets_key_is_carried_not_duplicated(self, override):
        override.write_text(
            yaml.safe_dump(
                {"targets": [{"name": "line1", "protocol": "modbus", "host": "10.0.0.5"}]}
            ),
            encoding="utf-8",
        )
        _run_init()
        raw = yaml.safe_load(override.read_text("utf-8"))
        assert "targets" not in raw
        assert [e["name"] for e in raw["endpoints"]] == ["line1", "press2"]


class TestHonoursTheIsolatedRoot:
    def test_without_the_override_it_writes_the_patched_default(self, monkeypatch):
        """The fixture moved CONFIG_FILE on the module; init must follow it."""
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        out = _run_init()
        assert _config_mod.CONFIG_FILE.exists()
        assert "via $" not in out
