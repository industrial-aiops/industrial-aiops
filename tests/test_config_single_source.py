"""One command must read one config file.

`IAIOPS_CONFIG` was resolved in `load_config_env()` only. The shared brain
modules (`historian_read`, `rca_history`) called that; the CLI's `get_manager()`
and every other caller called `load_config()`, which ignored it. So a single
`iaiops diag rca-live` read its ENDPOINTS from `~/.iaiops/config.yaml` and its
HISTORIAN from `$IAIOPS_CONFIG` — two different files, silently.

The visible failure is the mild one ("endpoint not found"). The one that matters
is quiet: point the override at a plant while a stale file sits in the home
directory, and the copilot pairs live evidence sampled from one machine with
history pulled from another. Nothing errors. Found 2026-08-24 driving
`diag rca-live` against a real Modbus device and a real IoTDB at once.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.config import (
    CONFIG_FILE,
    default_config_path,
    load_config,
    load_config_env,
)

pytestmark = pytest.mark.unit

_SITE = """
endpoints:
  - name: plant_a
    protocol: modbus
    host: 10.0.0.5
    port: 502
historian:
  reader: iotdb
  host: 10.0.0.6
  database: root.plant_a
"""


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "site.yaml"
    path.write_text(_SITE)
    monkeypatch.setenv("IAIOPS_CONFIG", str(path))
    return path


class TestTheOverrideAppliesToEveryLoader:
    def test_endpoints_come_from_the_override(self, site):
        """`load_config()` used to ignore it, which is where the split began."""
        assert [t.name for t in load_config().targets] == ["plant_a"]

    def test_the_historian_comes_from_the_same_file(self, site):
        assert load_config().historian.database == "root.plant_a"

    def test_both_loaders_agree(self, site):
        """Two loaders meant two answers to 'which file is this site configured in'."""
        direct, via_env = load_config(), load_config_env()
        assert [t.name for t in direct.targets] == [t.name for t in via_env.targets]
        assert direct.historian.reader == via_env.historian.reader

    def test_an_explicit_path_still_wins(self, tmp_path, site):
        """A caller that names a file means that file — the override is the default,
        not an ambush."""
        other = tmp_path / "other.yaml"
        other.write_text("endpoints: []\n")
        assert load_config(other).targets == ()

    def test_a_tilde_in_the_override_is_expanded(self, monkeypatch):
        monkeypatch.setenv("IAIOPS_CONFIG", "~/some-site.yaml")
        assert "~" not in str(default_config_path())

    def test_without_the_override_the_home_config_is_used(self, monkeypatch):
        monkeypatch.delenv("IAIOPS_CONFIG", raising=False)
        assert default_config_path() == CONFIG_FILE


class TestTheFrontEndsResolveTheSameTarget:
    def test_the_cli_manager_sees_the_override(self, site):
        """`resolve_target` went through `load_config(None)`, so the CLI was the
        half of the split that read the wrong file."""
        from iaiops.cli._common import get_manager

        assert get_manager().target("plant_a").name == "plant_a"

    def test_the_cli_and_the_historian_layer_agree(self, site):
        """The pairing that produced a wrong answer wearing the right shape: live
        evidence from one file, history from another."""
        from iaiops.cli._common import get_manager
        from iaiops.core.sink.historian_read import _resolve_reader

        assert get_manager().target("plant_a").host == "10.0.0.5"
        name, adapter = _resolve_reader(None)
        try:
            assert name == "iotdb"
        finally:
            adapter.close()
