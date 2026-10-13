"""`iaiops meter check|profile` and the shared engine both front-ends call."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from iaiops.core.brain.meter_analysis import analyse_hh, parse_summary

pytestmark = pytest.mark.unit
runner = CliRunner()

_HEAD = "MPAN,Date," + ",".join(f"HH{i:02d}" for i in range(1, 49))


def _csv(meters=("1200000000001",), days=7) -> str:
    rows = [_HEAD]
    for meter in meters:
        for d in range(days):
            vals = ["25" if 16 <= i < 36 else "5" for i in range(48)]
            rows.append(f"{meter},{12 + d:02d}/01/2026," + ",".join(vals))
    return "\n".join(rows) + "\n"


TARIFF_YAML = """
name: Two-rate
unit_rates:
  - {name: day, rate: 28, days: all, start: "07:00", end: "23:00"}
  - {name: night, rate: 16, days: all, start: "23:00", end: "07:00"}
standing_charge_p_per_day: 90
"""


@pytest.fixture
def cli():
    from iaiops.cli.meter import meter_app

    return meter_app


@pytest.fixture
def files(tmp_path):
    data = tmp_path / "hh.csv"
    data.write_text(_csv(), "utf-8")
    tariff = tmp_path / "tariff.yaml"
    tariff.write_text(TARIFF_YAML, "utf-8")
    return data, tariff


def test_engine_parse_summary():
    out = parse_summary(_csv())
    assert out["layout"] == "wide"
    expected = {"meter": "1200000000001", "intervals": 336}
    expected |= {"first_local": "2026-01-12 00:00", "last_local": "2026-01-18 23:30"}
    assert out["meters"] == [expected]


def test_engine_profile_with_tariff():
    tariff = {
        "unit_rates": [
            {"name": "flat", "rate": 30, "days": "all", "start": "00:00", "end": "24:00"}
        ]
    }
    out = analyse_hh(_csv(), tariff=tariff)
    one = out["profiles"]["1200000000001"]
    assert one["cost"]["avg_p_per_kwh"] == 30.0
    assert one["profile"]["coverage"]["coverage_pct"] == 100.0
    assert out["parse"]["layout"] == "wide"


def test_engine_omits_bulky_series_when_asked():
    out = analyse_hh(_csv(), include_series=False)
    profile = out["profiles"]["1200000000001"]["profile"]
    assert "heatmap" not in profile and "daily" not in profile


def test_check(cli, files):
    result = runner.invoke(cli, ["check", str(files[0]), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["counts"]["intervals"] == 336


def test_profile_json(cli, files):
    result = runner.invoke(cli, ["profile", str(files[0]), "--tariff", str(files[1]), "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["profiles"]["1200000000001"]["cost"]["tariff"] == "Two-rate"


def test_profile_human_output(cli, files):
    result = runner.invoke(cli, ["profile", str(files[0])])
    assert result.exit_code == 0, result.output
    assert "Out-of-hours" in result.output


def test_profile_writes_report(cli, files, tmp_path):
    out = tmp_path / "r.html"
    result = runner.invoke(
        cli, ["profile", str(files[0]), "--tariff", str(files[1]), "--report", str(out),
              "--site", "Test Club", "--hours", "mon-fri 08:00-18:00", "--holiday", "2026-01-12"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    page = out.read_text("utf-8")
    assert page.startswith("<!doctype html>") and "Test Club" in page


def test_report_needs_one_meter(cli, tmp_path):
    data = tmp_path / "two.csv"
    data.write_text(_csv(meters=("A", "B")), "utf-8")
    result = runner.invoke(cli, ["profile", str(data), "--report", str(tmp_path / "r.html")])
    assert result.exit_code == 1
    assert "--meter" in result.output


def test_bad_tariff_is_a_clean_error(cli, files, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("unit_rates: []\n", "utf-8")
    result = runner.invoke(cli, ["profile", str(files[0]), "--tariff", str(bad)])
    assert result.exit_code == 1
    assert "unit_rates" in result.output


def test_missing_file_is_a_clean_error(cli, tmp_path):
    result = runner.invoke(cli, ["check", str(tmp_path / "nope.csv")])
    assert result.exit_code == 1


def test_cp1252_file_is_read(cli, tmp_path):
    data = tmp_path / "excel.csv"
    data.write_bytes(_csv().replace("MPAN", "MPAN £").encode("cp1252"))
    result = runner.invoke(cli, ["check", str(data), "--json"])
    assert result.exit_code == 0, result.output


def test_registered_on_root():
    from iaiops.cli._root import app

    result = runner.invoke(app, ["meter", "--help"])
    assert result.exit_code == 0
    assert "profile" in result.output
