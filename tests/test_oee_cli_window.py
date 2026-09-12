"""`oee measure` end to end: the period it picks, and how it says where it came from.

`test_oee_default_window.py` covers the engine's rule. This covers the command,
because the defect was reachable by typing the default command and reading the
number next to "100% coverage" — no flag, no JSON, no engine call.
"""

from __future__ import annotations

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
    """A store holding 15s of samples from a run that PLANNED forty."""
    from iaiops.core.runtime import config as config_mod
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "cfgdir", raising=False)

    sink = SQLiteLocalSink(endpoint="line-1", protocol="modbus")
    sink.write(
        [
            {
                "metric": "40001",
                "value": 1,
                "numeric": True,
                "timestamp": (T0 + timedelta(seconds=i)).isoformat(),
            }
            for i in range(15)
        ]
    )
    return tmp_path


def _session(base_dir, duration_s=40):
    from iaiops.core.collect.plan import CollectionPlan
    from iaiops.core.collect.session import Session, save_session

    save_session(
        Session(
            run_id="run-demo",
            plan=CollectionPlan(
                endpoint="line-1", tags=("40001",), duration_s=duration_s, interval_ms=1000
            ),
            started_at=T0.isoformat(),
        ),
        base_dir=base_dir,
    )


def _measure(extra=None):
    from iaiops.cli._root import app

    return runner.invoke(app, ["oee", "measure", "line-1", "--json", *(extra or [])])


class TestTheDefaultCommand:
    def test_blindness_after_the_last_sample_is_reported_not_dropped(self, site):
        """The defect, through the command a person actually types.

        Before: `92.27% over 100% coverage, blind 0ms`. The blindness was real,
        recorded by `collect run`, and simply outside the period the report chose
        for itself.
        """
        _session(site / "cfgdir")
        result = _measure()
        assert result.exit_code == 0, result.output
        assert '"window_basis": "collection_run"' in result.output
        assert '"coverage_pct": 35.0' in result.output or '"unknown_s": 26.0' in result.output
        assert '"status": "insufficient_coverage"' in result.output, result.output

    def test_without_any_session_it_falls_back_and_says_which_basis_it_used(self, site):
        """Imported samples and historian reads have no session. The fallback is
        the old behaviour — and it has to be NAMED, because "100% coverage" means
        something different under each basis."""
        result = _measure()
        assert result.exit_code == 0, result.output
        assert '"window_basis": "sample_span"' in result.output

    def test_an_explicit_window_still_wins(self, site):
        """A session must never override what a person asked for."""
        _session(site / "cfgdir")
        result = _measure(
            ["--since", T0.isoformat(), "--until", (T0 + timedelta(seconds=14)).isoformat()]
        )
        assert '"window_basis": "requested"' in result.output


class TestTheRenderedReportStatesItsBasis:
    def test_the_human_output_names_where_the_period_came_from(self, site):
        from iaiops.cli._root import app

        _session(site / "cfgdir")
        result = runner.invoke(app, ["oee", "measure", "line-1"])
        assert result.exit_code == 0, result.output
        assert "period from" in result.output
        assert "collection run" in result.output

    def test_the_fallback_keeps_telling_you_to_scope_it(self, site):
        from iaiops.cli._root import app

        result = runner.invoke(app, ["oee", "measure", "line-1"])
        assert "--since" in result.output


def test_a_different_store_does_not_borrow_the_default_stores_session(site, tmp_path):
    """`--db` points at another body of samples; a window taken from a run we
    recorded against the default store would describe the wrong one."""
    _session(site / "cfgdir")
    from iaiops.cli._root import app
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    other = tmp_path / "elsewhere.db"
    SQLiteLocalSink(db_path=other, endpoint="line-1", protocol="modbus").write(
        [
            {
                "metric": "40001",
                "value": 1,
                "numeric": True,
                "timestamp": (T0 + timedelta(seconds=i)).isoformat(),
            }
            for i in range(15)
        ]
    )
    result = runner.invoke(app, ["oee", "measure", "line-1", "--json", "--db", str(other)])
    assert '"window_basis": "sample_span"' in result.output, result.output


class TestTheForwardableReportCarriesTheBasis:
    """The HTML report is the artifact that leaves the plant. A range nobody
    typed, with no provenance attached, is the one that gets read as "the line"."""

    def _render(self, basis):
        from iaiops.core.brain.oee_report import render_oee_report

        return render_oee_report(
            {
                "measured": {
                    "tag": "40001",
                    "status": "ok",
                    "availability": 0.9,
                    "coverage_pct": 100.0,
                    "running_s": 10.0,
                    "stopped_s": 1.0,
                    "unknown_s": 0.0,
                    "window": {
                        "start": "2026-09-12T13:00:00+00:00",
                        "end": "2026-09-12T13:00:40+00:00",
                    },
                    "window_basis": basis,
                },
                "factors": {"availability": 0.9, "performance": None, "quality": None},
                "oee": None,
                "losses": {},
                "production": None,
                "performance": {"performance": None},
                "quality": {"quality": None},
            },
            endpoint="line-1",
            site="",
            generated_at="2026-09-12T13:05:00+00:00",
        )

    def test_a_session_derived_period_says_so(self):
        assert "collection run that produced these samples" in self._render("collection_run")

    def test_the_sample_span_fallback_says_what_it_excludes(self):
        html = self._render("sample_span")
        assert "NOT counted as blind" in html
