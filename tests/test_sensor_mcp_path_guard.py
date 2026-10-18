"""The two sensor MCP tools that open a file read only inside the product's roots.

``sensor_import_iodd`` and ``sensor_profile_check`` take a path from the agent.
Over MCP that path is chosen by a model (or by a prompt injected into what it
read), so it is confined to ``$IAIOPS_HOME`` and the config directory — after
``..`` and symlinks are resolved — and a refusal never quotes the file. The CLI
is the operator's own shell and keeps reading the path they type.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import mcp_server.tools.sensor_tools as tools

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
IODD = ROOT / "tests" / "fixtures" / "iodd" / "distance_sensor.xml"

#: Distinctive values that must never appear in a refusal.
SECRET_ID = "LEAKED-ID-7f3a"
SECRET_PROTOCOL = "LEAKED-PROTOCOL-91c2"
PROBE = f"id: {SECRET_ID}\nprotocol: {SECRET_PROTOCOL}\nchannels: []\n"


@pytest.fixture
def outside(tmp_path_factory) -> Path:
    """A directory under neither $IAIOPS_HOME nor the config directory."""
    return tmp_path_factory.mktemp("outside-roots")


def _assert_refused(out: dict) -> str:
    error = out.get("error", "")
    assert "outside" in error, out
    assert "IAIOPS_HOME" in error  # the teaching error names the allowed roots
    assert SECRET_ID not in error and SECRET_PROTOCOL not in error
    assert "channels" not in out
    return error


# ── refused ──────────────────────────────────────────────────────────────────


def test_absolute_path_outside_the_roots_is_refused(outside):
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    _assert_refused(tools.sensor_profile_check(str(probe)))


def test_iodd_outside_the_roots_is_refused(outside):
    copy = outside / "device.xml"
    shutil.copy(IODD, copy)
    out = tools.sensor_import_iodd(str(copy))
    _assert_refused(out)
    assert "draft" not in out


def test_dotdot_traversal_out_of_home_is_refused(isolated_iaiops_home, outside):
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    # Starts inside $IAIOPS_HOME, climbs out of it.
    climbing = (
        isolated_iaiops_home / ".." / ".." / outside.parent.name / outside.name / "probe.yaml"
    )
    assert climbing.resolve() == probe.resolve()
    _assert_refused(tools.sensor_profile_check(str(climbing)))


def test_symlinked_directory_escaping_home_is_refused(isolated_iaiops_home, outside):
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    (isolated_iaiops_home / "profiles").symlink_to(outside, target_is_directory=True)
    _assert_refused(
        tools.sensor_profile_check(str(isolated_iaiops_home / "profiles" / "probe.yaml"))
    )


def test_symlinked_file_escaping_home_is_refused(isolated_iaiops_home, outside):
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    link = isolated_iaiops_home / "probe.yaml"
    link.symlink_to(probe)
    _assert_refused(tools.sensor_profile_check(str(link)))


def test_a_missing_file_outside_is_refused_as_outside_not_as_missing(outside):
    """Existence outside the roots is not an oracle the agent can probe."""
    missing = tools.sensor_profile_check(str(outside / "nope.yaml"))["error"]
    present_file = outside / "here.yaml"
    present_file.write_text(PROBE, "utf-8")
    present = tools.sensor_profile_check(str(present_file))["error"]
    assert missing.replace("nope.yaml", "X") == present.replace("here.yaml", "X")


def test_in_root_yaml_syntax_error_does_not_quote_the_file(isolated_iaiops_home):
    bad = isolated_iaiops_home / "bad.yaml"
    bad.write_text(f"id: {SECRET_ID}\nprotocol: [{SECRET_PROTOCOL}\n", "utf-8")
    error = tools.sensor_profile_check(str(bad))["error"]
    assert "not valid YAML" in error and "line" in error
    assert SECRET_ID not in error and SECRET_PROTOCOL not in error


# ── allowed ──────────────────────────────────────────────────────────────────


def test_a_profile_under_iaiops_home_is_read(isolated_iaiops_home):
    draft_dir = isolated_iaiops_home / "profiles"
    draft_dir.mkdir()
    iodd = draft_dir / "device.xml"
    shutil.copy(IODD, iodd)
    draft = tools.sensor_import_iodd(str(iodd))
    assert "error" not in draft, draft
    profile = draft_dir / "tof.yaml"
    profile.write_text(draft["draft"], "utf-8")
    out = tools.sensor_profile_check(str(profile))
    assert "error" not in out, out
    assert {c["channel"] for c in out["channels"]} >= {"distance"}


def test_the_config_directory_is_a_root_of_its_own(tmp_path_factory, monkeypatch):
    """CONFIG_DIR outside $IAIOPS_HOME still admits files (conftest nests them)."""
    from iaiops.core.runtime import config

    config_dir = tmp_path_factory.mktemp("config-dir")
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    shutil.copy(IODD, config_dir / "device.xml")
    assert "error" not in tools.sensor_import_iodd(str(config_dir / "device.xml"))


def test_an_iaiops_config_override_does_not_add_its_directory(outside, monkeypatch):
    """IAIOPS_CONFIG=/etc/plant.yaml must not make /etc readable to the agent."""
    monkeypatch.setenv("IAIOPS_CONFIG", str(outside / "config.yaml"))
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    _assert_refused(tools.sensor_profile_check(str(probe)))


def test_a_relative_path_inside_home_is_read(isolated_iaiops_home, monkeypatch):
    shutil.copy(IODD, isolated_iaiops_home / "device.xml")
    monkeypatch.chdir(isolated_iaiops_home)
    assert "error" not in tools.sensor_import_iodd("device.xml")


# ── the CLI is the operator's shell, not an agent ────────────────────────────


def test_cli_still_reads_a_path_the_operator_types(outside):
    from typer.testing import CliRunner

    from iaiops.cli import app

    iodd = outside / "device.xml"
    shutil.copy(IODD, iodd)
    result = CliRunner().invoke(app, ["sensor", "import-iodd", str(iodd)])
    assert result.exit_code == 0, result.output
    assert "待核实" in result.output


# ── a root too broad to confine anything is not a root ───────────────────────


def test_config_in_the_home_directory_does_not_open_the_whole_home(tmp_path_factory, monkeypatch):
    """IAIOPS_CONFIG=~/config.yaml must not make every file in $HOME readable."""
    home = tmp_path_factory.mktemp("user-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("IAIOPS_CONFIG", str(home / "config.yaml"))
    downloads = home / "Downloads"
    downloads.mkdir()
    probe = downloads / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    _assert_refused(tools.sensor_profile_check(str(probe)))


def test_config_at_the_filesystem_root_does_not_open_the_filesystem(outside, monkeypatch):
    monkeypatch.setenv("IAIOPS_CONFIG", "/config.yaml")
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    _assert_refused(tools.sensor_profile_check(str(probe)))


def test_iaiops_home_set_to_the_home_directory_is_dropped(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("user-home2")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("IAIOPS_HOME", str(home))
    probe = home / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    _assert_refused(tools.sensor_profile_check(str(probe)))


# ── more escape attempts ─────────────────────────────────────────────────────


def test_relative_dotdot_from_inside_home_is_refused(isolated_iaiops_home, outside, monkeypatch):
    probe = outside / "probe.yaml"
    probe.write_text(PROBE, "utf-8")
    monkeypatch.chdir(isolated_iaiops_home)
    rel = Path("..") / ".." / outside.parent.name / outside.name / "probe.yaml"
    assert (isolated_iaiops_home / rel).resolve() == probe.resolve()
    _assert_refused(tools.sensor_profile_check(str(rel)))


def test_null_byte_is_refused_without_reading(isolated_iaiops_home):
    out = tools.sensor_profile_check(str(isolated_iaiops_home / "a\x00.yaml"))
    assert "error" in out and "channels" not in out


def test_a_long_path_does_not_push_the_roots_out_of_the_refusal(outside):
    error = tools.sensor_profile_check(str(outside / ("a" * 5000 + ".yaml")))["error"]
    assert "IAIOPS_HOME" in error and str(Path(outside).resolve()) not in error[:60]


# ── errors from files inside the roots quote nothing from them ───────────────


@pytest.mark.parametrize(
    "body",
    [
        f"id: x\nprotocol: !{SECRET_ID} modbus\n",  # unknown tag
        f"id: *{SECRET_ID}\n",  # undefined alias
    ],
)
def test_yaml_problem_text_does_not_quote_tags_or_aliases(isolated_iaiops_home, body):
    bad = isolated_iaiops_home / "bad.yaml"
    bad.write_text(body, "utf-8")
    error = tools.sensor_profile_check(str(bad))["error"]
    assert "not valid YAML" in error and SECRET_ID not in error


def test_non_utf8_files_report_only_that(isolated_iaiops_home):
    (isolated_iaiops_home / "bin.yaml").write_bytes(b"\xff\xfe" + SECRET_ID.encode())
    (isolated_iaiops_home / "bin.xml").write_bytes(b"\xff\xfe" + SECRET_ID.encode())
    for out in (
        tools.sensor_profile_check(str(isolated_iaiops_home / "bin.yaml")),
        tools.sensor_import_iodd(str(isolated_iaiops_home / "bin.xml")),
    ):
        assert "not UTF-8 text" in out["error"] and "0xff" not in out["error"]
