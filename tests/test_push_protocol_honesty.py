"""What a PUSHED data source must not let the rest of the product believe.

Every defect pinned here was found by pointing the collector at a real mosquitto
broker on the lab network with a spec-shaped Sparkplug node publishing into it —
alias-only NDATA, periodic re-BIRTH, epoch-millisecond metric timestamps. The
green suite had nothing to say about any of them, because a synthetic payload is
written the way the decoder expects and a synthetic clock is already ISO-8601.

The shape they share: a limit or a habit of the TOOL (the poller's rate, a
missing capability, a timestamp format, a config key) reaching the customer as a
fact about their plant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.unit


@dataclass
class _Target:
    name: str = "uns"
    protocol: str = "mqtt"
    host: str = "127.0.0.1"
    port: int = 1883
    topic: str = "#"
    stale_after_s: float = 30.0
    tags: tuple = field(default_factory=tuple)


# --- 1. a device timestamp must reach the store AS a timestamp -------------------


class TestTimestampsArriveAsTimestamps:
    @pytest.mark.parametrize(
        ("raw", "epoch_s"),
        [
            (1789521121683, 1789521121.683),  # Sparkplug states epoch MILLISECONDS
            ("1789521121683", 1789521121.683),
            (1789521121, 1789521121.0),  # a JSON envelope: epoch seconds
        ],
    )
    def test_epoch_forms_become_the_instant_they_name(self, raw, epoch_s):
        from iaiops.connectors.sparkplug.tap import _iso_ts

        assert _iso_ts(raw) == datetime.fromtimestamp(epoch_s, UTC).isoformat()

    def test_a_stated_date_is_kept(self):
        from iaiops.connectors.sparkplug.tap import _iso_ts

        assert _iso_ts("2026-09-16T00:32:01+00:00") == "2026-09-16T00:32:01+00:00"

    @pytest.mark.parametrize("raw", [42, 0, -1, "", None, True, "n/a", 4_000_000_000_000_000])
    def test_what_is_not_a_time_yields_nothing_rather_than_a_date(self, raw):
        """A counter is not a time. Inventing 1970 from it would be worse than
        having none — the caller falls back to the observation time instead."""
        from iaiops.connectors.sparkplug.tap import _iso_ts

        assert _iso_ts(raw) == ""

    def test_a_sparkplug_metric_is_stored_with_a_parseable_time(self):
        """Reproduced live: rows landed as `1789521121683`, so `oee measure` found
        0 usable samples in a store holding 74, `export --since` returned nothing,
        and `store prune` offered to delete rows collected 90 seconds earlier."""
        from iaiops.connectors.sparkplug.tap import UnsTap
        from iaiops.core.brain._shared import parse_ts

        tap = UnsTap(client=object(), target=_Target())
        stamp = int(datetime.now(UTC).timestamp() * 1000)
        tap._put("Line1/Edge1:PartCount", 331, _iso(stamp))
        _value, ts = tap.read("Line1/Edge1:PartCount")
        assert parse_ts(ts) is not None, ts

    def test_a_payload_that_states_no_time_is_stamped_when_it_arrived(self):
        from iaiops.connectors.sparkplug.tap import UnsTap
        from iaiops.core.brain._shared import parse_ts

        tap = UnsTap(client=object(), target=_Target())
        tap._put("plant/line2/level", 40.0, "")
        _value, ts = tap.read("plant/line2/level")
        assert parse_ts(ts) is not None and ts

    def test_re_reading_returns_the_same_observation_time(self):
        """The cache is the same publish until the publisher sends another."""
        from iaiops.connectors.sparkplug.tap import UnsTap

        tap = UnsTap(client=object(), target=_Target())
        tap._put("plant/line2/level", 40.0, "")
        first = tap.read("plant/line2/level")[1]
        assert tap.read("plant/line2/level")[1] == first


def _iso(epoch_ms: int) -> str:
    from iaiops.connectors.sparkplug.tap import _iso_ts

    return _iso_ts(epoch_ms)


# --- 2. re-reading a cached publish is not a second observation ------------------


class TestRepeatsAreNotSamples:
    def _run(self, timestamps, db):
        from iaiops.core.collect.plan import CollectionPlan
        from iaiops.core.collect.runner import run_collection

        stamps = list(timestamps)

        class _Clock:
            def __init__(self):
                self.now = 1_000_000.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds or 1.0

        def read(_target, _ref):
            return 1.0, stamps.pop(0) if len(stamps) > 1 else stamps[0]

        plan = CollectionPlan(
            endpoint="uns", tags=("a",), duration_s=len(timestamps), interval_ms=1000
        )
        return run_collection(plan, target=object(), reader=read, db_path=db, clock=_Clock())

    def test_the_same_publish_polled_five_times_is_one_sample(self, tmp_path):
        """Live: 96 rows held 20 publishes. Coverage, the cadence every blind-gap
        limit is derived from, and the run's claimed resolution were all inflated."""
        from iaiops.core.sink.sqlite_local import store_coverage

        db = tmp_path / "d.db"
        result = self._run(["2026-09-16T01:40:24+00:00"] * 5, db)
        assert result.samples_written == 1
        assert result.repeats == 4
        assert store_coverage(db)["samples"] == 1

    def test_a_repeat_still_counts_as_covered(self, tmp_path):
        """The point WAS live at that tick — it just had not been republished."""
        result = self._run(["2026-09-16T01:40:24+00:00"] * 4, tmp_path / "d.db")
        assert result.coverage_pct == 100.0

    def test_a_protocol_that_states_no_time_writes_every_tick(self, tmp_path):
        """A polled device answers freshly each time; nothing here may suppress it."""
        result = self._run(["", "", ""], tmp_path / "d.db")
        assert result.samples_written == 3 and result.repeats == 0

    def test_a_new_publish_after_repeats_is_written(self, tmp_path):
        stamps = [
            "2026-09-16T01:40:24+00:00",
            "2026-09-16T01:40:24+00:00",
            "2026-09-16T01:40:25+00:00",
        ]
        result = self._run(stamps, tmp_path / "d.db")
        assert result.samples_written == 2 and result.repeats == 1


# --- 3. a missing capability is not a fault at the site --------------------------


class TestAMissingCapabilityIsNotASiteFault:
    def test_no_per_ref_read_says_so_instead_of_diagnosing_the_network(self):
        """Live: a topic publishing every second was diagnosed
        `comms_ok_value_unreadable` — "the point does not exist on this device"."""
        from iaiops.core.brain.diagnostics import _read_ref, _score_read_hops

        # The connection is fine — the tap is subscribed. It is the per-ref READ
        # that this build does not have for a push protocol.
        assert _read_ref(_Target(), "plant/line2/level").get("unsupported") is True
        out = _score_read_hops(_Target(), "plant/line2/level", 60, [])
        assert out["verdict"] == "no_per_ref_read_in_this_build"
        assert "NOTHING about the point or the network" in out["diagnosis"]

    def test_rca_draws_no_cause_from_it(self):
        from iaiops.core.brain.rca import _score_dataflow

        contributions: dict = {}
        _score_dataflow({"verdict": "no_per_ref_read_in_this_build"}, contributions)
        assert contributions == {}

    def test_a_real_unreadable_point_still_reads_as_one(self):
        from iaiops.core.brain.rca import _score_dataflow

        contributions: dict = {}
        _score_dataflow({"verdict": "comms_ok_value_unreadable"}, contributions)
        assert "comms_loss" in contributions


# --- 4. readiness grades the ENDPOINT, not just the protocol ---------------------


class TestReadinessGradesTheEndpoint:
    def test_a_broker_without_stale_after_s_is_not_ready_to_collect(self):
        """Live: readiness said "Continuous collection — ready" and the very next
        command refused, because the tap requires stale_after_s."""
        from iaiops.core.collect.reader import collectable_reason

        assert "stale_after_s" in collectable_reason(_Target(stale_after_s=0))
        assert collectable_reason(_Target()) == ""

    def test_the_requirement_names_the_endpoint_and_the_reason(self):
        from iaiops.core.readiness.assess import assess

        @dataclass
        class _Config:
            targets: tuple = ()

        report = assess(_Config(targets=(_Target(stale_after_s=0),)))
        reqs = [r for cap in report.capabilities for r in cap.requirements]
        req = next(r for r in reqs if r.key == "collectable_endpoint")
        assert req.met is False
        assert "uns" in req.detail and "stale_after_s" in req.detail

    def test_a_protocol_with_no_point_read_still_reads_as_the_protocol_s_limit(self):
        from iaiops.core.collect.reader import collectable_reason

        assert "no point-read path" in collectable_reason(_Target(protocol="mtconnect"))


# --- 5. a '#' filter does not say which kind of namespace this is ----------------


class TestTheWholeTreeFilterTeachesBothRules:
    def _points_step(self, topic):
        from iaiops.core.onboard.uns_steps import _uns_points_step

        return _uns_points_step((_Target(topic=topic),))

    def test_it_refuses_to_pick_a_ref_rule_it_cannot_know(self):
        """Live: a Sparkplug site was handed `spBv1.0/Line1/NDATA/Edge1` as a ref;
        collection then refused it as never-published — the tool's own wrong
        answer, reported as the site's mistake."""
        state, detail, command = self._points_step("#")
        assert "does not say which kind of namespace" in detail
        assert "group/edge[/device]:metric" in detail and "the topic itself" in detail
        assert "mqtt browse" in command

    def test_a_stated_sparkplug_filter_still_gets_the_sparkplug_rule(self):
        _state, detail, command = self._points_step("spBv1.0/#")
        assert "live-schema" in command and "group/edge[/device]:metric" in detail

    def test_a_stated_plain_filter_still_gets_the_topic_rule(self):
        _state, detail, command = self._points_step("plant/#")
        assert "mqtt browse" in command and "the topic itself" in detail


# --- 6. printed output must survive the console ---------------------------------


class TestPrintedTextIsNotEatenByMarkup:
    def test_onboard_prints_a_ref_that_contains_brackets(self, tmp_path, monkeypatch):
        """`[/device]` is a closing tag to rich: it raised on the UNS points step."""
        from typer.testing import CliRunner

        from iaiops.cli._root import app

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "endpoints:\n  - name: uns\n    protocol: mqtt\n    host: 10.0.0.5\n"
            "    topic: '#'\n    stale_after_s: 30\n"
        )
        monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
        result = CliRunner().invoke(app, ["onboard", "status", "--db", str(tmp_path / "n.db")])
        assert result.exit_code == 0, result.output
        assert "group/edge[/device]:metric" in " ".join(result.output.split())

    def test_tags_apply_prints_running_when_with_its_value(self, tmp_path, monkeypatch):
        """`running_when: [true]` printed as `running_when:` — pasting it gave
        null. `--out` was always correct; the path the banner points at was not."""
        from typer.testing import CliRunner

        from iaiops.cli._root import app

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "endpoints:\n  - name: uns\n    protocol: mqtt\n    host: 10.0.0.5\n"
            "    topic: 'plant/#'\n    stale_after_s: 30\n    tags:\n"
            "      - ref: plant/l1/run\n"
        )
        monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
        sheet = tmp_path / "s.csv"
        sheet.write_text("ref,endpoint,role,label,running_when\nplant/l1/run,uns,run_state,,true\n")
        result = CliRunner().invoke(app, ["tags", "apply", str(sheet), "--by", "wei"])
        assert result.exit_code == 0, result.output
        assert "running_when: [true]" in result.output


# --- 7. a row whose age cannot be read is never "old enough to delete" -----------


class TestPruneNeverDeletesWhatItCannotDate:
    def test_an_undated_row_is_kept_and_counted(self, tmp_path):
        """Live: `ts` held epoch text, which sorts before every real date, so a
        prune reported 74 minutes-old rows as older than a 30-day cutoff."""
        from iaiops.core.retain.policy import RetentionPolicy
        from iaiops.core.retain.prune import plan_prune, prune
        from iaiops.core.sink.sqlite_local import SQLiteLocalSink

        db = tmp_path / "data.db"
        sink = SQLiteLocalSink(db_path=db, endpoint="uns", protocol="mqtt")
        sink.write([{"metric": "t", "value": 1, "numeric": True, "timestamp": "1789521121683"}])
        sink.close()
        policy = RetentionPolicy(raw_days=30)
        planned = plan_prune(db, policy)
        assert planned["rows_to_remove"] == 0
        assert planned["rows_undated_kept"] == 1
        done = prune(db, policy, sealed_before=datetime.now(UTC), apply=True)
        assert done["rows_removed"] == 0 and done["rows_kept"] == 1

    def test_a_dated_row_past_the_cutoff_is_still_removed(self, tmp_path):
        from iaiops.core.retain.policy import RetentionPolicy
        from iaiops.core.retain.prune import prune
        from iaiops.core.sink.sqlite_local import SQLiteLocalSink

        db = tmp_path / "data.db"
        sink = SQLiteLocalSink(db_path=db, endpoint="uns", protocol="mqtt")
        sink.write(
            [{"metric": "t", "value": 1, "numeric": True, "timestamp": "2020-01-01T00:00:00+00:00"}]
        )
        sink.close()
        done = prune(db, RetentionPolicy(raw_days=30), sealed_before=datetime.now(UTC), apply=True)
        assert done["rows_removed"] == 1
