"""A malformed typed Modbus point is refused before a run starts (HLD §16.5 S2).

Inside a run, a ref that cannot be parsed fails on every tick — on a held
session that also drops and reopens the connection each time. A week-long run
would then be a week of gaps that a typo caused. So the plan refuses it first.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from iaiops.core.collect.reader import ref_problems

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_modbus_refs_are_checked_against_the_grammar():
    target = SimpleNamespace(protocol="modbus")
    problems = ref_problems(target, ("40", "ir:0:float32:CDAB", "ir:0:float32", "tank"))
    assert len(problems) == 2
    assert "order" in problems[0] and "grammar" in problems[1]


def test_other_protocols_are_not_second_guessed():
    assert ref_problems(SimpleNamespace(protocol="opcua"), ("ns=2;s=x", "anything")) == []


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config = {
        "targets": [
            {
                "name": "sensor",
                "protocol": "modbus",
                "host": "127.0.0.1",
                "port": 5020,
                "tags": [{"ref": "ir:0:float32", "label": "force"}],
            }
        ]
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("IAIOPS_CONFIG", str(path))
    return path


def test_collect_plan_refuses_a_float32_without_word_order(configured):
    from iaiops.cli.collect import collect_app

    result = runner.invoke(collect_app, ["plan", "sensor", "--duration", "1h"])
    assert result.exit_code == 1
    assert "word" in result.output and "order" in result.output


def test_collect_plan_accepts_typed_refs(configured):
    from iaiops.cli.collect import collect_app

    result = runner.invoke(
        collect_app, ["plan", "sensor", "--duration", "1h", "--tags", "ir:0:float32:CDAB,40"]
    )
    assert result.exit_code == 0, result.output
