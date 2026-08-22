"""Readiness — the answer to "what can I run today, and what is each gap waiting for".

Three properties carry this feature, and each is the kind that decays quietly:

* **It emits nothing.** A readiness check that had to touch the plant would not
  get run on a site you have not been authorised to probe — which is exactly the
  site that most needs one. Asserted by making every probe path explode.
* **It never fills in.** Which tag is the production counter is process
  knowledge. A wrong guess produces plausible-looking OEE numbers, which is
  considerably worse than an error (HLD §9.4, D16).
* **`degraded` is not `blocked`.** Root-cause analysis without a historian still
  ranks causes; it just cannot see the drift before the stoppage. Collapsing the
  two would tell a site that has something useful today that it has nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from iaiops.core.readiness import BLOCKED, DEGRADED, READY, assess
from iaiops.core.readiness.assess import (
    BASELINE_MIN_SAMPLES,
    BASELINE_MIN_SPAN_DAYS,
    gather_facts,
)
from iaiops.core.sink.sqlite_local import SQLiteLocalSink, store_coverage

pytestmark = pytest.mark.unit


@dataclass
class FakeTarget:
    name: str
    protocol: str
    tags: tuple = ()


@dataclass
class FakeConfig:
    targets: tuple = ()
    historian: object = None


@dataclass
class FakeHistorian:
    reader: str = "sqlite"


UNCONFIGURED = FakeConfig()


def store_with(tmp_path, tag="PT-204", n=160, days=4):
    """A local store holding ``n`` samples of one tag spread over ``days``."""
    db = tmp_path / "d.db"
    sink = SQLiteLocalSink(db_path=db, endpoint="line1", protocol="opcua")
    sink.write(
        [
            {
                "metric": tag,
                "value": 1.0 + i * 0.01,
                "numeric": True,
                "timestamp": f"2026-08-{1 + (i * days) // n:02d}T{i % 24:02d}:00:00+00:00",
            }
            for i in range(n)
        ]
    )
    sink.close()
    return db


def cap(report, key):
    return next(c for c in report.capabilities if c.key == key)


class TestItEmitsNothing:
    def test_no_probe_path_is_reachable(self, monkeypatch, tmp_path):
        """Same posture as `scan plan`: a check you can run anywhere, including a
        network you have no permission to touch."""
        import socket

        from iaiops.core.discovery import runner as runner_mod
        from iaiops.core.discovery import sweep as sweep_mod

        def explode(*args, **kwargs):
            raise AssertionError("readiness contacted something — it must not")

        monkeypatch.setattr(sweep_mod, "probe_port", explode)
        monkeypatch.setattr(runner_mod, "run_scan", explode)
        monkeypatch.setattr(socket, "create_connection", explode)
        monkeypatch.setattr(socket.socket, "connect", explode)

        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert report.capabilities

    def test_it_says_so_in_the_notes(self, tmp_path):
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert any("Nothing was contacted" in n for n in report.notes)


class TestABlankSite:
    def test_only_the_survey_is_ready(self, tmp_path):
        """The answer a first-time user needs: one thing works, here is the rest."""
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert [c.key for c in report.by_status(READY)] == ["site_survey"]

    def test_the_survey_needs_nothing_but_a_range(self, tmp_path):
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert cap(report, "site_survey").status == READY

    def test_a_missing_store_is_not_a_fault(self, tmp_path):
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert any("not a fault" in n for n in report.notes)

    def test_an_unreadable_config_is_reported_as_unconfigured(self, monkeypatch, tmp_path):
        """That IS the first-time state, and it is the one this command exists for."""

        def boom():
            raise FileNotFoundError("no config.yaml")

        monkeypatch.setattr("iaiops.core.runtime.config.load_config", boom)
        report = assess(db_path=tmp_path / "none.db")
        assert any("has not been configured yet" in n for n in report.notes)
        assert cap(report, "site_survey").status == READY

    def test_every_blocked_row_still_explains_what_is_missed(self, tmp_path):
        """A blocked row that did not say what it was for would just be a scold."""
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        for capability in report.capabilities:
            assert capability.value, f"{capability.key} has no stated value"
            assert len(capability.value) > 25


class TestDegradedIsNotBlocked:
    def _site(self, tmp_path, historian=None):
        cfg = FakeConfig(
            targets=(FakeTarget("line1", "opcua", ({"ref": "PT-204"},)),), historian=historian
        )
        return assess(config=cfg, db_path=store_with(tmp_path))

    def test_rca_without_a_historian_still_runs(self, tmp_path):
        """It ranks causes; it just cannot see the drift before the stoppage."""
        rca = cap(self._site(tmp_path), "downtime_rca")
        assert rca.status == DEGRADED
        assert "runs, but without" in rca.headline
        assert [r.key for r in rca.missing_optional] == ["historian"]

    def test_a_historian_makes_it_ready(self, tmp_path):
        rca = cap(self._site(tmp_path, historian=FakeHistorian()), "downtime_rca")
        assert rca.status == READY

    def test_the_missing_historian_explains_the_consequence(self, tmp_path):
        rca = cap(self._site(tmp_path), "downtime_rca")
        fix = next(r for r in rca.missing_optional if r.key == "historian").fix
        assert "CURRENT" in fix and "before a stoppage" in fix

    def test_missing_tags_blocks_rather_than_degrades(self, tmp_path):
        """No tag list is not a reduced analysis — there is nothing to correlate."""
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ()),))
        rca = cap(assess(config=cfg, db_path=store_with(tmp_path)), "downtime_rca")
        assert rca.status == BLOCKED


class TestTheAlarmSourceIsContextual:
    """Optional for root cause, required for alarm governance — the same fact,
    weighted by what each capability is actually made of."""

    def _modbus_site(self, tmp_path):
        cfg = FakeConfig(
            targets=(FakeTarget("plc1", "modbus", ({"ref": "40001"},)),),
            historian=FakeHistorian(),
        )
        return assess(config=cfg, db_path=store_with(tmp_path))

    def test_rca_only_degrades_without_alarms(self, tmp_path):
        assert cap(self._modbus_site(tmp_path), "downtime_rca").status == DEGRADED

    def test_alarm_governance_is_blocked_without_them(self, tmp_path):
        governance = cap(self._modbus_site(tmp_path), "alarm_governance")
        assert governance.status == BLOCKED
        assert [r.key for r in governance.missing_required] == ["alarm_source"]

    def test_the_reason_names_the_protocol_limit(self, tmp_path):
        governance = cap(self._modbus_site(tmp_path), "alarm_governance")
        assert "opcua" in governance.requirements[0].detail


class TestItNeverFillsIn:
    def test_oee_reports_the_mapping_as_inexpressible(self, tmp_path):
        """Not "you forgot to configure it" — there is no field to configure.
        Saying otherwise sends someone hunting for a setting that does not exist."""
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),))
        oee = cap(assess(config=cfg, db_path=store_with(tmp_path)), "oee")
        mapping = next(r for r in oee.requirements if r.key == "oee_role_mapping")
        assert mapping.met is False
        assert mapping.expressible is False
        assert mapping.as_dict()["not_yet_expressible"] is True

    def test_it_offers_the_route_that_does_exist(self, tmp_path):
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),))
        oee = cap(assess(config=cfg, db_path=store_with(tmp_path)), "oee")
        mapping = next(r for r in oee.requirements if r.key == "oee_role_mapping")
        assert "analytics oee" in mapping.fix

    def test_no_capability_is_satisfied_by_inference(self, tmp_path):
        """Every met requirement must point at something actually found."""
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),))
        report = assess(config=cfg, db_path=store_with(tmp_path))
        for capability in report.capabilities:
            for req in capability.requirements:
                if req.met:
                    assert req.detail, f"{capability.key}/{req.key} met with no evidence"

    def test_a_tag_list_is_never_guessed_from_collected_samples(self, tmp_path):
        """The store holds PT-204, but nobody said it MATTERS. Promoting a
        collected tag into 'the tags that matter' would be exactly the guess
        this command refuses to make."""
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ()),))
        report = assess(config=cfg, db_path=store_with(tmp_path, tag="PT-204"))
        rca = cap(report, "downtime_rca")
        assert "monitored_tags" in {r.key for r in rca.missing_required}


class TestBaselineHistoryMatchesTheRealLearner:
    def test_the_thresholds_do_not_drift_from_the_learner(self):
        """If these diverge, the report promises a baseline the learner would
        then refuse to produce — a readiness check that is confidently wrong."""
        from iaiops.core.brain import baseline

        assert BASELINE_MIN_SAMPLES == baseline.DEFAULT_MIN_SAMPLES
        assert BASELINE_MIN_SPAN_DAYS == baseline.DEFAULT_MIN_SPAN_S / 86_400.0

    def test_thin_history_blocks_with_the_numbers_shown(self, tmp_path):
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),))
        report = assess(config=cfg, db_path=store_with(tmp_path, n=10, days=1))
        band = cap(report, "baseline_alerting")
        assert band.status == BLOCKED
        detail = next(r for r in band.requirements if r.key == "baseline_history").detail
        assert "10" in detail and str(BASELINE_MIN_SAMPLES) in detail

    def test_enough_history_unblocks_it(self, tmp_path):
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),))
        report = assess(config=cfg, db_path=store_with(tmp_path, n=160, days=4))
        assert cap(report, "baseline_alerting").status == READY

    def test_the_refusal_is_framed_as_the_feature(self, tmp_path):
        cfg = FakeConfig(targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),))
        report = assess(config=cfg, db_path=store_with(tmp_path, n=10, days=1))
        fix = next(
            r for r in cap(report, "baseline_alerting").requirements if r.key == "baseline_history"
        ).fix
        assert "false alarms" in fix


class TestTheActionableView:
    def test_blocked_on_ranks_by_how_much_each_gap_unlocks(self, tmp_path):
        """A site usually unlocks several scenarios by supplying one thing."""
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert report.blocked_on
        counts = [int(entry.split("unlocks ")[1].rstrip(")")) for entry in report.blocked_on]
        assert counts == sorted(counts, reverse=True)

    def test_a_fully_ready_site_has_nothing_to_report(self, tmp_path):
        cfg = FakeConfig(
            targets=(FakeTarget("line1", "opcua", ({"ref": "x"},)),), historian=FakeHistorian()
        )
        report = assess(config=cfg, db_path=store_with(tmp_path))
        # OEE stays blocked by construction, so the site is never "all ready" —
        # and that is the honest state until a role mapping can be expressed.
        assert report.summary[BLOCKED] == 1
        assert cap(report, "oee").status == BLOCKED

    def test_the_facts_ride_along_so_a_row_can_be_checked(self, tmp_path):
        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        assert "store" in report.facts and "endpoints" in report.facts

    def test_the_report_serializes_for_a_second_front_end(self, tmp_path):
        """The engine returns structure; CLI and an App page only render (D17)."""
        import json

        report = assess(config=UNCONFIGURED, db_path=tmp_path / "none.db")
        blob = json.dumps(report.as_dict())
        assert "site_survey" in blob and "blocked_on" in blob


class TestStoreCoverage:
    def test_a_missing_store_reports_absence_not_zero_history(self, tmp_path):
        assert store_coverage(tmp_path / "nope.db")["exists"] is False

    def test_span_comes_from_the_best_covered_tag(self, tmp_path):
        """Baselines are learned PER TAG, so an overall span is a promise the tag
        you care about may not be able to keep.

        The fixture is built so the two answers DIFFER: neither tag has more than
        two days of its own history, while the store as a whole spans ten. A span
        taken store-wide would report ten days and imply a baseline is learnable,
        when the learner would refuse on every tag present.
        """
        db = tmp_path / "d.db"
        sink = SQLiteLocalSink(db_path=db, endpoint="e", protocol="modbus")
        sink.write(
            [
                {"metric": "early", "value": 1, "numeric": True, "timestamp": t}
                for t in ("2026-08-01T00:00:00+00:00", "2026-08-03T00:00:00+00:00")
            ]
            + [
                {"metric": "late", "value": 2, "numeric": True, "timestamp": t}
                for t in ("2026-08-09T00:00:00+00:00", "2026-08-11T00:00:00+00:00")
            ]
        )
        sink.close()

        coverage = store_coverage(db)
        assert coverage["tags"] == 2
        # The store spans ten days end to end...
        assert coverage["oldest"].startswith("2026-08-01")
        assert coverage["newest"].startswith("2026-08-11")
        # ...but no single tag does, and that is the number that decides.
        assert coverage["span_days"] == 2.0, coverage
        assert coverage["best_covered_tag"] in {"early", "late"}

    def test_an_unparseable_timestamp_yields_no_span_rather_than_a_guess(self, tmp_path):
        db = tmp_path / "d.db"
        sink = SQLiteLocalSink(db_path=db, endpoint="e", protocol="modbus")
        sink.write([{"metric": "t", "value": 1, "numeric": True, "timestamp": "not-a-time"}])
        sink.close()
        assert store_coverage(db)["span_days"] == 0.0


class TestFacts:
    def test_protocols_are_deduplicated(self, tmp_path):
        cfg = FakeConfig(
            targets=(
                FakeTarget("a", "opcua"),
                FakeTarget("b", "opcua"),
                FakeTarget("c", "modbus"),
            )
        )
        facts = gather_facts(cfg, tmp_path / "none.db")
        assert facts["protocols"] == ["modbus", "opcua"]
        assert facts["endpoints"] == 3

    def test_alarm_capable_endpoints_are_named(self, tmp_path):
        cfg = FakeConfig(targets=(FakeTarget("a", "opcua"), FakeTarget("b", "modbus")))
        assert gather_facts(cfg, tmp_path / "none.db")["alarm_capable_endpoints"] == ["a"]
