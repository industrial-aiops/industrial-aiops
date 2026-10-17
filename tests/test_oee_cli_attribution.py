"""`oee measure` says how many of the stoppages it found have a reason a person gave.

`test_oee_stop_attribution.py` covers the join. This covers the command, because a
pure function nobody calls is how `six_big_losses` sat unreachable for months.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.unit

runner = CliRunner()
T0 = datetime(2026, 9, 12, 13, 0, 0, tzinfo=UTC)

_CONFIG = """endpoints:
  - name: line-1
    protocol: modbus
    host: 127.0.0.1
    port: 5020
    tags:
      - label: "Run"
        ref: "40001"
        role: run_state
        running_when: [1]
"""


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A store holding 1000s of samples with one 400s stop at t=300."""
    from iaiops.core.runtime import config as config_mod
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cfgdir", raising=False)
    SQLiteLocalSink(endpoint="line-1", protocol="modbus").write(
        [
            {
                "metric": "40001",
                "value": 0 if 300 <= i < 700 else 1,
                "numeric": True,
                "timestamp": (T0 + timedelta(seconds=i)).isoformat(),
            }
            for i in range(1000)
        ]
    )
    return tmp_path


def _measure(*extra):
    from iaiops.cli._root import app

    result = runner.invoke(app, ["oee", "measure", "line-1", "--json", *extra])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_the_payload_carries_the_attribution(site):
    out = _measure()
    attribution = out["stop_attribution"]
    assert attribution["stops"] == 1
    assert attribution["classes"]["no_case"]["count"] == 1
    assert attribution["reasons_from_signal"] == 0


def test_a_confirmed_case_is_counted_as_a_persons_reason(site):
    from iaiops.core.knowledge.case_store import confirm_case, open_case

    onset = _measure()["measured"]["stop_windows"][0]["onset"]
    case = open_case("default", "line-1", onset)
    confirm_case("default", case.incident_id, "mechanical_fault", by="li")
    out = _measure()
    assert out["stop_attribution"]["classes"]["person_confirmed"]["count"] == 1
    # And a different case site holds no such answer.
    other = _measure("--case-site", "plant-b")
    assert other["stop_attribution"]["classes"]["person_confirmed"]["count"] == 0


def test_the_human_output_names_who_gave_reasons(site):
    from iaiops.cli._root import app

    result = runner.invoke(app, ["oee", "measure", "line-1"])
    assert result.exit_code == 0, result.output
    assert "Stoppage reasons" in result.output
    assert "never put to a person" in result.output
