"""The two journeys `onboard` now tells apart — and the refusals that keep it honest.

A site whose data already flows through an MQTT/UNS broker was told to scan the
network first. A scan never identifies MQTT (it is deliberately left out of
identification), so the first command such a site got led to a dead end. The
journey is now derived before any step is graded:

    devices — no UNS yet: survey → endpoints → points → MEANING → collect → ask
    uns     — already on a broker: connect → namespace → points → MEANING → …

and on `uns` a stored namespace audit forks it into B1 (clean) and B2 (governance
is the work). What is guarded below is mostly what the path must NOT claim:
a journey it cannot derive, a B1 it has no audit for, a clean namespace from an
audit that saw nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest
from test_onboard import _resolve
from typer.testing import CliRunner

from iaiops.core.onboard.model import (
    STATE_DONE,
    STATE_NEXT,
    TRACK_DEVICES,
    TRACK_MIXED,
    TRACK_UNDECIDED,
    TRACK_UNS,
)
from iaiops.core.onboard.path import assess_path, resolve_track
from iaiops.core.sink.uns_audit_store import (
    audit_file,
    broker_id,
    load_uns_audit,
    save_uns_audit,
)

pytestmark = pytest.mark.unit
runner = CliRunner()


@dataclass
class Tag:
    ref: str
    role: str = ""
    label: str = ""


@dataclass
class Target:
    name: str
    protocol: str
    tags: tuple = ()
    topic: str = ""
    stale_after_s: float = 0.0
    host: str = "10.0.0.5"
    port: int = 1883


@dataclass
class Config:
    targets: tuple = field(default_factory=tuple)


def _broker(name="uns-1", topic="plant/#", stale=30.0, tags=()):
    return Target(name, "mqtt", tags=tags, topic=topic, stale_after_s=stale)


def _audit(endpoint, verdict="clean", findings=0, topics=12, topic="#"):
    return {
        "verdict": verdict,
        "sprawl_findings": findings,
        "topic_count": topics,
        "capture": {"endpoint": endpoint, "observed_messages": 40, "topic": topic},
    }


def _save(target, tmp_path, verdict="clean", findings=0):
    """An audit stored the way the front ends store one: this broker, a naming
    standard, and a capture that stayed well under its cap."""
    return save_uns_audit(
        _audit(target.name, verdict, findings, topic=target.topic),
        endpoint=target.name,
        broker=broker_id(target),
        allowed_roots=["plant"],
        min_segments=2,
        max_msgs=500,
        duration_s=30,
        base_dir=tmp_path / "audits",
    )


def _path(config, tmp_path, track="auto"):
    return assess_path(
        config, db_path=tmp_path / "none.db", track=track, audit_dir=tmp_path / "audits"
    )


def _commands_in(text):
    return re.findall(r"`(iaiops [^`]+)`", text or "")


def _every_command(path):
    """Everything this path can tell someone to type — commands, choices, and the
    commands quoted inside details and notes. Each must parse."""
    out = []
    for step in path.steps:
        if step.command:
            out.append(step.command)
        out += [cmd for _, cmd in step.choices]
        out += _commands_in(step.detail)
    for note in path.notes:
        out += _commands_in(note)
    return out


def _claims_subtrack(path):
    """Whether ``track_detail`` ASSERTS a subtrack.

    The honest wording for "no audit yet" names B1 and B2 too — "B1 or B2 is
    unknown until it is" — so a substring check for "B1" fails on the very message
    that refuses to claim one, and ``"B1" in detail`` PASSES on it. The claim is
    what has to be looked for, and the path writes a claim as "B1 — " / "B2 — ".
    """
    return re.search(r"\bB[12] — ", path.track_detail) is not None


def _assert_no_subtrack_claimed(path):
    assert not _claims_subtrack(path), path.track_detail
    assert "unknown" in path.track_detail, path.track_detail


class TestTheJourneyIsDerivedNotGuessed:
    @pytest.mark.parametrize(
        ("targets", "expected"),
        [
            ((), TRACK_UNDECIDED),
            ((Target("plc", "modbus"),), TRACK_DEVICES),
            ((_broker(),), TRACK_UNS),
            ((Target("plc", "modbus"), _broker()), TRACK_MIXED),
        ],
    )
    def test_auto_reads_it_off_config(self, targets, expected):
        assert resolve_track(Config(targets), "auto")[0] == expected

    def test_an_explicit_track_wins(self):
        assert resolve_track(Config((Target("plc", "modbus"),)), "uns")[0] == TRACK_UNS

    def test_an_unknown_track_is_refused_with_the_vocabulary(self):
        with pytest.raises(ValueError, match="devices"):
            resolve_track(Config(), "broker")


class TestWhenTheFilesCannotSayItAsks:
    def test_nothing_configured_offers_both_journeys_and_picks_neither(self, tmp_path):
        path = _path(Config(), tmp_path)
        assert path.track == TRACK_UNDECIDED
        assert len(path.steps) == 1 and path.steps[0].state == STATE_NEXT
        assert path.steps[0].command == "", "a question has no single command"
        assert len(path.steps[0].choices) == 2
        for command in _every_command(path):
            _resolve(command)

    def test_a_mixed_site_is_not_silently_put_on_either_journey(self, tmp_path):
        path = _path(Config((Target("plc", "modbus"), _broker())), tmp_path)
        assert path.track == TRACK_MIXED
        assert [cmd for _, cmd in path.steps[0].choices] == [
            "iaiops onboard status --track devices",
            "iaiops onboard status --track uns",
        ]

    def test_a_stored_scan_is_mentioned_but_not_taken_as_the_answer(self, tmp_path, monkeypatch):
        """A scan usually means the devices journey — but a UNS site can scan too."""
        import iaiops.core.onboard.path as path_mod

        monkeypatch.setattr(path_mod, "_scan_count", lambda _db: (3, ""))
        path = _path(Config(), tmp_path)
        assert path.track == TRACK_UNDECIDED
        assert "3 scan(s) are stored" in path.steps[0].detail
        assert len(path.steps[0].choices) == 2

    def test_a_broken_config_is_not_offered_a_journey_choice(self, tmp_path, monkeypatch):
        """Choosing a journey over a file that will not load is choosing blind."""
        broken = tmp_path / "config.yaml"
        broken.write_text("endpoints:\n  - name: e1\n   protocol: mqtt\n")
        monkeypatch.setenv("IAIOPS_CONFIG", str(broken))
        path = assess_path(None, db_path=tmp_path / "none.db", audit_dir=tmp_path / "a")
        assert path.steps[0].choices == ()
        assert "did not parse" in path.steps[0].detail


class TestTheUnsJourneyNeverScans:
    def test_its_steps_start_at_the_broker(self, tmp_path):
        path = _path(Config((_broker(),)), tmp_path)
        keys = [s.key for s in path.steps]
        assert keys == ["connect", "namespace", "points", "meaning", "collect", "answers"]
        assert not any("scan" in cmd for cmd in _every_command(path)), (
            "a scan never identifies MQTT — sending a UNS site to one is a dead end"
        )

    def test_a_broker_without_stale_after_s_cannot_be_connected(self, tmp_path):
        path = _path(Config((_broker(stale=0),)), tmp_path)
        connect = path.steps[0]
        assert connect.state == STATE_NEXT and "stale_after_s" in connect.detail

    def test_every_command_on_the_uns_journey_parses(self, tmp_path):
        for topic in ("plant/#", "spBv1.0/#"):
            path = _path(Config((_broker(topic=topic),)), tmp_path)
            for command in _every_command(path):
                _resolve(command)

    def test_sparkplug_is_listed_with_live_schema_and_plain_mqtt_with_browse(self, tmp_path):
        save_uns_audit(_audit("uns-1"), base_dir=tmp_path / "audits")
        spb = _path(Config((_broker(topic="spBv1.0/#"),)), tmp_path)
        plain = _path(Config((_broker(topic="plant/#"),)), tmp_path)
        points = next(s for s in spb.steps if s.key == "points")
        assert "live-schema" in points.command
        assert "group/edge[/device]:metric" in points.detail
        assert "mqtt browse" in next(s for s in plain.steps if s.key == "points").command


class TestB1AndB2ComeOnlyFromAStoredAudit:
    def test_never_audited_is_neither_b1_nor_b2(self, tmp_path):
        path = _path(Config((_broker(),)), tmp_path)
        namespace = path.steps[1]
        assert namespace.state == STATE_NEXT
        assert "uns-live-audit" in namespace.command
        _assert_no_subtrack_claimed(path)

    def test_a_clean_audit_is_b1(self, tmp_path):
        broker = _broker()
        _save(broker, tmp_path)
        path = _path(Config((broker,)), tmp_path)
        assert path.steps[1].state == STATE_DONE
        assert "B1 — " in path.track_detail, path.track_detail

    def test_a_sprawling_sparkplug_audit_is_b2_and_names_the_drift_watch(self, tmp_path):
        broker = _broker(topic="spBv1.0/#")
        _save(broker, tmp_path, "sprawling", findings=9)
        path = _path(Config((broker,)), tmp_path)
        assert "B2 — " in path.track_detail, path.track_detail
        commands = [cmd for note in path.notes for cmd in _commands_in(note)]
        assert any("uns-live-drift" in cmd for cmd in commands), path.notes
        for command in commands:
            _resolve(command)

    def test_b2_on_plain_mqtt_offers_no_drift_watch_that_could_never_fire(self, tmp_path):
        """Both schema commands read Sparkplug BIRTHs; on a plain topic tree they
        return an empty schema and report "no drift" forever."""
        broker = _broker(topic="plant/#")
        _save(broker, tmp_path, "sprawling", findings=9)
        path = _path(Config((broker,)), tmp_path)
        assert "B2 — " in path.track_detail, path.track_detail
        commands = [cmd for note in path.notes for cmd in _commands_in(note)]
        assert not any("uns-live-drift" in cmd for cmd in commands), path.notes
        assert any("no schema-drift watch for plain MQTT" in note for note in path.notes)

    def test_an_audit_that_saw_no_topics_is_not_stored_and_is_not_b1(self, tmp_path):
        """The flattering reading this store exists to refuse: an empty capture has
        no findings, and "no findings" must not become "clean"."""
        empty = {
            "error": "No topics. Pass a list of UNS topic strings.",
            "capture": {"endpoint": "uns-1", "observed_messages": 0},
        }
        assert save_uns_audit(empty, base_dir=tmp_path / "audits") is None
        path = _path(Config((_broker(),)), tmp_path)
        _assert_no_subtrack_claimed(path)
        assert path.steps[1].state == STATE_NEXT

    def test_an_unreadable_stored_audit_is_a_file_problem_not_a_verdict(self, tmp_path):
        target = audit_file("uns-1", tmp_path / "audits")
        target.parent.mkdir(parents=True)
        target.write_text("{not json")
        path = _path(Config((_broker(),)), tmp_path)
        assert "could not be read" in path.steps[1].detail
        _assert_no_subtrack_claimed(path)

    def test_another_endpoints_audit_is_not_borrowed_through_a_file_name_collision(self, tmp_path):
        save_uns_audit(_audit("line 1"), base_dir=tmp_path / "audits")  # file: line_1.json
        assert load_uns_audit("line_1", base_dir=tmp_path / "audits") is None


class TestTheDevicesJourneyIsUnchanged:
    def test_a_device_only_site_still_starts_with_the_survey(self, tmp_path):
        path = _path(Config((Target("plc", "modbus"),)), tmp_path)
        assert [s.key for s in path.steps][:3] == ["survey", "endpoints", "points"]
        assert path.track == TRACK_DEVICES

    def test_a_forced_journey_on_a_mixed_site_points_at_the_other_half(self, tmp_path):
        path = _path(Config((Target("plc", "modbus"), _broker())), tmp_path, track="uns")
        assert path.track == TRACK_UNS
        assert any("--track devices" in note for note in path.notes), path.notes

    def test_a_mixed_site_is_not_offered_the_claim_that_it_has_no_broker(self, tmp_path):
        path = _path(Config((Target("plc", "modbus"), _broker())), tmp_path)
        labels = " ".join(label for label, _ in path.steps[0].choices)
        assert "NOT in a broker" not in labels, labels
        assert {cmd for _, cmd in path.steps[0].choices} == {
            "iaiops onboard status --track devices",
            "iaiops onboard status --track uns",
        }


class TestBothFrontEnds:
    def _site(self, tmp_path, monkeypatch, body):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(body)
        monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))

    def test_the_cli_refuses_an_unknown_track(self, tmp_path, monkeypatch):
        from iaiops.cli._root import app

        self._site(tmp_path, monkeypatch, "endpoints: []\n")
        result = runner.invoke(app, ["onboard", "status", "--track", "broker", "--json"])
        assert result.exit_code != 0
        assert "devices" in result.output

    def test_the_cli_json_carries_both_choices_on_an_empty_site(self, tmp_path, monkeypatch):
        import json

        from iaiops.cli._root import app

        self._site(tmp_path, monkeypatch, "endpoints: []\n")
        result = runner.invoke(app, ["onboard", "status", "--json", "--db", str(tmp_path / "n.db")])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["track"] == TRACK_UNDECIDED
        assert len(payload["next_choices"]) == 2

    def test_the_mcp_tool_is_the_engine_answer_verbatim(self, tmp_path, monkeypatch):
        from mcp_server.tools import overview_tools

        self._site(
            tmp_path,
            monkeypatch,
            "endpoints:\n  - name: uns-1\n    protocol: mqtt\n    host: 10.0.0.5\n"
            "    topic: 'plant/#'\n    stale_after_s: 30\n    tags: []\n",
        )
        db = tmp_path / "n.db"
        assert (
            overview_tools.onboarding_status(db=str(db), track="uns")
            == assess_path(db_path=db, track="uns").as_dict()
        )
