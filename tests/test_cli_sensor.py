"""`iaiops sensor import-iodd | check` — the CLI over the profile engine."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

pytestmark = pytest.mark.unit

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "iodd" / "distance_sensor.xml"


@pytest.fixture
def cli():
    from iaiops.cli.sensor import sensor_app

    return sensor_app


def test_import_iodd_writes_a_draft_that_check_accepts(cli, tmp_path):
    out = tmp_path / "profiles" / "tof.yaml"
    result = runner.invoke(cli, ["import-iodd", str(FIXTURE), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "待核实" in result.output and "Label" in result.output  # draft + not-imported
    assert yaml.safe_load(out.read_text("utf-8"))["source"] == "iodd"
    checked = runner.invoke(cli, ["check", str(out)])
    assert checked.exit_code == 0, checked.output
    assert "distance" in checked.output and "待核实" in checked.output


def test_import_iodd_refuses_to_overwrite_without_force(cli, tmp_path):
    out = tmp_path / "tof.yaml"
    out.write_text("keep me", "utf-8")
    result = runner.invoke(cli, ["import-iodd", str(FIXTURE), "--out", str(out)])
    assert result.exit_code == 1 and "--force" in result.output
    assert out.read_text("utf-8") == "keep me"
    forced = runner.invoke(cli, ["import-iodd", str(FIXTURE), "--out", str(out), "--force"])
    assert forced.exit_code == 0, forced.output


def test_import_iodd_without_out_prints_the_draft(cli):
    result = runner.invoke(cli, ["import-iodd", str(FIXTURE)])
    assert result.exit_code == 0, result.output
    assert "iodd-888-4660" in result.output


def test_check_reports_a_broken_profile(cli, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: x\nprotocol: modbus\nsource: manual\nverified: maybe\nchannels: []\n", "utf-8"
    )
    result = runner.invoke(cli, ["check", str(bad)])
    assert result.exit_code == 1 and "at least one channel" in result.output


def test_sensor_group_is_registered_and_governed():
    from iaiops.cli._root import app

    names = {group.name for group in app.registered_groups}
    assert "sensor" in names
