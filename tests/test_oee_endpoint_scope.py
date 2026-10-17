"""OEE reads ONE endpoint's samples, never a neighbour's that share its ref.

Modbus refs are register numbers, so "40001" on line-1 and "40001" on line-2 are
the same string. The store labels every row with the endpoint that was polled;
`oee measure` and `case open` filtered by tag alone, so line-1's availability was
computed over line-2's run-state too, and its part count included line-2's
parts. Which way that points depends on the neighbour — it can make a line look
better OR worse than it ran, and nothing on the page says it happened.

Rows written with no endpoint label (the sink's '' default) cannot be assigned
to a line. They are never counted toward one: alone, they are refused with the
reason; beside labeled rows, they are left out and the count is stated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.unit

runner = CliRunner()
T0 = datetime(2026, 9, 12, 13, 0, 0, tzinfo=UTC)
SINCE = T0.isoformat()
UNTIL = (T0 + timedelta(seconds=59)).isoformat()


def _endpoint(name: str, port: int) -> str:
    return f"""  - name: {name}
    protocol: modbus
    host: 127.0.0.1
    port: {port}
    tags:
      - label: "Run"
        ref: "40001"
        role: run_state
        running_when: [1]
      - label: "Parts"
        ref: "40010"
        role: total_count
"""


_CONFIG = "endpoints:\n" + _endpoint("line-1", 5020) + _endpoint("line-2", 5021)


def _write(endpoint: str, ref: str, values) -> None:
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    SQLiteLocalSink(endpoint=endpoint, protocol="modbus").write(
        [
            {
                "metric": ref,
                "value": v,
                "numeric": True,
                "timestamp": (T0 + timedelta(seconds=i)).isoformat(),
            }
            for i, v in enumerate(values)
        ]
    )


@pytest.fixture
def config(tmp_path, monkeypatch):
    from iaiops.core.runtime import config as config_mod

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cfgdir", raising=False)
    return tmp_path


@pytest.fixture
def two_lines(config):
    """line-1 ran the whole minute; line-2 stopped halfway. Their part counters differ 10x."""
    _write("line-1", "40001", [1] * 60)
    _write("line-2", "40001", [1] * 30 + [0] * 30)
    _write("line-1", "40010", list(range(60)))
    _write("line-2", "40010", [i * 10 for i in range(60)])
    return config


def _measure(endpoint: str):
    from iaiops.cli._root import app

    return runner.invoke(
        app, ["oee", "measure", endpoint, "--since", SINCE, "--until", UNTIL, "--json"]
    )


def test_availability_reads_only_this_endpoint(two_lines):
    one, two = _measure("line-1"), _measure("line-2")
    assert one.exit_code == 0, one.output
    assert two.exit_code == 0, two.output
    assert json.loads(one.output)["measured"]["availability"] == 1.0
    assert 0.4 < json.loads(two.output)["measured"]["availability"] < 0.6


def test_part_count_reads_only_this_endpoint(two_lines):
    result = _measure("line-1")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["production"]["produced"] == 59.0


def test_no_unlabeled_rows_means_nothing_excluded(two_lines):
    measured = json.loads(_measure("line-1").output)["measured"]
    assert measured["unlabeled_samples_excluded"] == 0


def test_only_unlabeled_rows_is_refused_with_the_reason(config):
    _write("", "40001", [1] * 60)
    result = _measure("line-1")
    assert result.exit_code == 1
    text = " ".join(result.output.split())
    assert "no endpoint label" in text
    assert "40001" in text


def test_unlabeled_rows_beside_labeled_ones_are_excluded_and_counted(config):
    _write("line-1", "40001", [1] * 60)
    # A stop nobody can place on a line. Counting it would make line-1 look
    # stopped; it must neither be counted nor vanish without a word.
    _write("", "40001", [0] * 60)
    _write("", "40010", [i * 10 for i in range(60)])
    _write("line-1", "40010", list(range(60)))
    payload = json.loads(_measure("line-1").output)
    assert payload["measured"]["availability"] == 1.0
    assert payload["production"]["produced"] == 59.0
    assert payload["measured"]["unlabeled_samples_excluded"] == 120
    assert "no endpoint label" in payload["measured"]["note"]


def test_case_open_reads_only_this_endpoint(two_lines):
    from iaiops.cli._root import app

    result = runner.invoke(app, ["case", "open", "line-1", "--min-stop-s", "10", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["stoppages_found"] == 0


def test_case_open_refuses_only_unlabeled_rows(config):
    from iaiops.cli._root import app

    _write("", "40001", [0] * 60)
    result = runner.invoke(app, ["case", "open", "line-1", "--json"])
    assert result.exit_code == 1
    assert "no endpoint label" in " ".join(result.output.split())
