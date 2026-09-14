"""Guards a first round of mutation testing showed were missing.

Sixteen mutations were applied to the journey code; six survived the original
tests. Each test below exists because one specific mutation passed without it,
and the reason it passed is named — because the reasons are the lesson:

* a fixture where correct and broken code behave identically;
* a guarantee tested at the store but never through either front end that
  actually writes to it;
* a property of the output (its age, its scope) that nothing looked at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from typer.testing import CliRunner

from iaiops.core.onboard.model import STATE_DONE, STATE_NEXT
from iaiops.core.onboard.path import assess_path
from iaiops.core.sink.uns_audit_store import (
    audit_file,
    broker_id,
    load_uns_audit,
    save_uns_audit,
)

pytestmark = pytest.mark.unit
runner = CliRunner()

_UNS_CONFIG = (
    "endpoints:\n"
    "  - name: uns-1\n"
    "    protocol: mqtt\n"
    "    host: 10.0.0.5\n"
    "    port: 1883\n"
    "    topic: 'plant/#'\n"
    "    stale_after_s: 30\n"
    "    tags: []\n"
)


@dataclass
class Tag:
    ref: str
    role: str = ""
    label: str = ""
    running_when: tuple = ()


@dataclass
class Target:
    name: str
    protocol: str
    tags: tuple = ()
    topic: str = ""
    stale_after_s: Any = 0.0
    host: str = ""
    port: int = 0


@dataclass
class Config:
    targets: tuple = field(default_factory=tuple)


def _broker(tags=(), name="uns-1", host="10.0.0.5", port=1883, topic="plant/#", stale=30.0):
    return Target(name, "mqtt", tags=tags, topic=topic, stale_after_s=stale, host=host, port=port)


def _save(result, target, tmp_path, *, roots=("plant",), depth=2, cap=500, duration=30, now=None):
    """Store an audit the way a front end does — for THIS endpoint and broker,
    with the site's naming standard — unless a test deliberately withholds one."""
    return save_uns_audit(
        result,
        endpoint=target.name,
        broker=broker_id(target),
        allowed_roots=list(roots),
        min_segments=depth,
        max_msgs=cap,
        duration_s=duration,
        base_dir=tmp_path / "audits",
        now=now,
    )


def _audit(verdict="clean", findings=0, topics=12, endpoint="uns-1", topic="plant/#", observed=40):
    return {
        "verdict": verdict,
        "sprawl_findings": findings,
        "topic_count": topics,
        "capture": {"endpoint": endpoint, "observed_messages": observed, "topic": topic},
    }


def _path(config, tmp_path, track="auto"):
    return assess_path(
        config, db_path=tmp_path / "none.db", track=track, audit_dir=tmp_path / "audits"
    )


def _step(path, key):
    return next(s for s in path.steps if s.key == key)


def test_an_audit_with_a_verdict_but_zero_topics_is_not_stored(tmp_path):
    """Survived: dropping the `topics` check from save_uns_audit.

    The original test used a result with no verdict at all, so `not verdict`
    refused it first and the topic check was never reached — correct and broken
    code returned the same None. A result that DOES carry a verdict but saw zero
    topics is the one that discriminates.
    """
    degenerate = _audit("clean", findings=0, topics=0)
    assert save_uns_audit(degenerate, base_dir=tmp_path / "audits") is None
    assert load_uns_audit("uns-1", base_dir=tmp_path / "audits") is None


def test_a_minor_verdict_is_neither_b1_nor_b2(tmp_path):
    """`minor` is one to five heuristic findings. Calling it B1 reports findings as
    their absence; calling it B2 — reproduced on a spec-correct Sparkplug tree whose
    STATE topic is a depth outlier — states a heuristic as a governance verdict."""
    broker = _broker()
    _save(_audit("minor", findings=3), broker, tmp_path)
    path = _path(Config((broker,)), tmp_path)
    assert "B2 — " not in path.track_detail, path.track_detail
    assert "B1 — " not in path.track_detail
    namespace = _step(path, "namespace")
    assert namespace.state == STATE_NEXT and "review" in namespace.detail


def test_the_uns_journey_does_not_grade_itself_on_the_device_endpoints(tmp_path):
    """Survived: building the journey's view from ALL endpoints.

    A mixed site forced onto the UNS journey, where only the DEVICE endpoint has
    declared roles. Graded on every endpoint, the meaning step reads the device's
    run_state and total_count and reports the broker journey's semantics as done
    when no broker point has any meaning declared.
    """
    plc = Target(
        "plc",
        "modbus",
        tags=(Tag("40001", "run_state", running_when=(1,)), Tag("40002", "total_count")),
    )
    path = _path(Config((plc, _broker())), tmp_path, track="uns")
    meaning = _step(path, "meaning")
    assert meaning.state != STATE_DONE, meaning.detail
    assert "40001" not in meaning.detail and "40002" not in meaning.detail


def test_the_age_of_a_stored_audit_is_stated(tmp_path):
    """Survived: dropping the age from the namespace step.

    An audit is a point-in-time snapshot. A verdict shown without its age reads as
    a statement about the namespace NOW, and a topic tree can sprawl in a month.
    """
    three_days_ago = datetime.now(UTC) - timedelta(days=3)
    broker = _broker()
    _save(_audit("clean"), broker, tmp_path, now=three_days_ago)
    path = _path(Config((broker,)), tmp_path)
    namespace = _step(path, "namespace")
    assert "3 day(s) ago" in namespace.detail, namespace.detail


def _patched_live_audit(monkeypatch):
    from iaiops.connectors.sparkplug import live

    monkeypatch.setattr(
        live,
        "uns_live_audit",
        lambda target, *a, **k: _audit(
            "sprawling", findings=7, topics=90, endpoint=getattr(target, "name", "")
        ),
    )


def test_the_cli_audit_command_leaves_its_verdict_for_onboard(tmp_path, monkeypatch):
    """Survived: removing the save from `iaiops mqtt uns-live-audit`.

    Every earlier test called save_uns_audit directly, so the store was proven
    and the front end that is supposed to write to it was not.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_UNS_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    _patched_live_audit(monkeypatch)
    from iaiops.cli._root import app

    result = runner.invoke(
        app, ["mqtt", "uns-live-audit", "--endpoint", "uns-1", "--duration-s", "1"]
    )
    assert result.exit_code == 0, result.output
    assert '"stored_for_onboard": true' in result.output, result.output
    record = load_uns_audit("uns-1")
    assert record is not None and record.verdict == "sprawling", record


def test_the_mcp_audit_tool_leaves_its_verdict_for_onboard(tmp_path, monkeypatch):
    """Survived: removing the save from the MCP `uns_live_audit` tool (D17)."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_UNS_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    _patched_live_audit(monkeypatch)
    from mcp_server.tools import sparkplug_tools

    out = sparkplug_tools.uns_live_audit(endpoint="uns-1", duration_s=1)
    assert out.get("stored_for_onboard") is True, out
    record = load_uns_audit("uns-1")
    assert record is not None and record.verdict == "sprawling", record


# --- engine review findings, each reproduced before it was fixed -------------


def test_clean_without_a_naming_standard_is_not_b1(tmp_path):
    """F1. Without --root and --min-segments two of the six checks cannot fire, so
    the command onboard printed produced "clean" largely from its own defaults."""
    broker = _broker()
    _save(_audit("clean"), broker, tmp_path, roots=(), depth=0)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail, path.track_detail
    assert "not established" in path.track_detail
    namespace = _step(path, "namespace")
    assert namespace.state == STATE_NEXT and "--root" in namespace.command


def test_a_capture_that_hit_its_message_cap_cannot_make_b1(tmp_path):
    """F2. A busy broker fills 500 messages in seconds; clean on part is not clean."""
    broker = _broker()
    _save(_audit("clean", observed=500), broker, tmp_path, cap=500)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail, path.track_detail
    assert "cap" in _step(path, "namespace").detail


def test_an_audit_of_a_different_broker_does_not_count(tmp_path):
    """F3. Same endpoint name, repointed at another broker."""
    old = _broker(host="10.0.0.5")
    _save(_audit("clean"), old, tmp_path)
    path = _path(Config((_broker(host="10.9.9.9"),)), tmp_path)
    assert "B1 — " not in path.track_detail, path.track_detail
    assert "now points at" in _step(path, "namespace").detail


def test_an_audit_of_a_narrower_topic_filter_does_not_count(tmp_path):
    broker = _broker(topic="plant/#")
    _save(_audit("clean", topic="plant/line1/#"), broker, tmp_path)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail, path.track_detail


def test_an_audit_of_the_whole_tree_covers_a_narrower_endpoint_and_is_b1(tmp_path):
    broker = _broker(topic="plant/#")
    _save(_audit("clean", topic="#"), broker, tmp_path)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " in path.track_detail, path.track_detail
    assert _step(path, "namespace").state == STATE_DONE


def test_b1_states_the_age_of_its_oldest_audit(tmp_path):
    """F4. The journey line is what gets read; it must say how old its evidence is."""
    broker = _broker()
    _save(_audit("clean"), broker, tmp_path, now=datetime.now(UTC) - timedelta(days=400))
    path = _path(Config((broker,)), tmp_path)
    assert "oldest audit 400 day(s) ago" in path.track_detail, path.track_detail


def test_a_future_dated_audit_is_a_file_problem_not_fresh_evidence(tmp_path):
    broker = _broker()
    _save(_audit("clean"), broker, tmp_path, now=datetime.now(UTC) + timedelta(days=3650))
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail
    assert "dated in the future" in _step(path, "namespace").detail


def _write_raw(tmp_path, endpoint, doc):
    import json

    target = audit_file(endpoint, tmp_path / "audits")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc))


@pytest.mark.parametrize(
    ("field_name", "value", "why"),
    [
        ("topic_count", 0, "topic_count"),
        ("sprawl_findings", "lots", "sprawl_findings"),
        ("audited_at", None, "no valid date"),
        ("observed_messages", 0, "observed no messages"),
    ],
)
def test_load_refuses_what_save_would_refuse(tmp_path, field_name, value, why):
    """F5. A hand-edited file must not become a verdict the save side would refuse."""
    doc = {
        "version": 3,
        "duration_s": 30,
        "endpoint": "uns-1",
        "verdict": "clean",
        "sprawl_findings": 0,
        "topic_count": 12,
        "observed_messages": 40,
        "audited_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "topic_filter": "#",
        "broker": "10.0.0.5:1883",
        "allowed_roots": ["plant"],
        "min_segments": 2,
        "max_msgs": 500,
        "capture_capped": False,
    }
    doc[field_name] = value
    _write_raw(tmp_path, "uns-1", doc)
    record = load_uns_audit("uns-1", base_dir=tmp_path / "audits")
    assert record is not None and why in record.error, record


def test_a_long_endpoint_name_cannot_borrow_anothers_verdict(tmp_path):
    """F6. The capture truncates names to 64; a file named from that let A read B's."""
    a = "line-" + "x" * 59
    b = a + "-2"
    _save(_audit("clean", endpoint=b[:64]), _broker(name=b), tmp_path)
    assert load_uns_audit(a, base_dir=tmp_path / "audits") is None
    assert load_uns_audit(b, base_dir=tmp_path / "audits") is not None


def test_a_possibly_truncated_capture_name_is_refused_without_an_explicit_endpoint(tmp_path):
    long_name = "x" * 64
    assert save_uns_audit(_audit(endpoint=long_name), base_dir=tmp_path / "audits") is None


def test_two_non_ascii_endpoint_names_do_not_overwrite_each_other(tmp_path):
    """N2. Both sanitised to the same file name and the second audit replaced the first."""
    for name in ("第一", "第二"):
        _save(_audit("clean", endpoint=name), _broker(name=name), tmp_path)
    assert load_uns_audit("第一", base_dir=tmp_path / "audits") is not None
    assert load_uns_audit("第二", base_dir=tmp_path / "audits") is not None


def test_a_result_carrying_an_error_is_not_stored(tmp_path):
    """F9. The refusal must be the store's own, not the producer's good behaviour."""
    bad = {**_audit("clean"), "error": "broker refused"}
    assert _save(bad, _broker(), tmp_path) is None


def _write_samples(db, endpoint, count=50):
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    start = datetime.now(UTC) - timedelta(hours=1)
    SQLiteLocalSink(db_path=db, endpoint=endpoint, protocol="x").write(
        [
            {
                "metric": "t1",
                "value": 1,
                "numeric": True,
                "timestamp": (start + timedelta(seconds=i)).isoformat(),
            }
            for i in range(count)
        ]
    )


def test_a_b2_site_can_never_read_as_every_step_done(tmp_path):
    """F7. Sprawling audit, roles declared, samples collected: the note said
    governance was the work while the path said everything was finished."""
    broker = _broker(
        tags=(Tag("plant/run", "run_state", running_when=(1,)), Tag("plant/good", "total_count"))
    )
    _save(_audit("sprawling", findings=40), broker, tmp_path)
    _write_samples(tmp_path / "none.db", "uns-1")
    path = _path(Config((broker,)), tmp_path)
    assert path.next_step is not None, [s.state for s in path.steps]
    assert path.next_step.key == "namespace"


def test_the_uns_journey_counts_only_broker_samples(tmp_path):
    """F8. A devices-only site forced onto uns was shown collect: done from a PLC."""
    plc = Target("plc", "opcua")
    _write_samples(tmp_path / "none.db", "plc", count=500)
    path = _path(Config((plc,)), tmp_path, track="uns")
    assert _step(path, "collect").state != STATE_DONE
    assert _step(path, "answers").state != STATE_DONE


def test_forcing_devices_on_a_broker_site_does_not_claim_it_has_no_endpoints(tmp_path):
    """N1. "no endpoints in config.yaml" was false, and no note warned that a scan
    never identifies the broker."""
    path = _path(Config((_broker(),)), tmp_path, track="devices")
    endpoints = _step(path, "endpoints")
    assert "belong to the uns journey" in endpoints.detail, endpoints.detail
    assert any("--track uns" in note for note in path.notes), path.notes


def test_an_unreadable_audit_directory_is_reported_not_raised(tmp_path):
    """N3. `exists()` sat outside the try, so a permission error crashed the path."""
    import os

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads through permissions")
    locked = tmp_path / "audits"
    locked.mkdir()
    locked.chmod(0)
    try:
        path = _path(Config((_broker(),)), tmp_path)
    finally:
        locked.chmod(0o700)
    assert "could not be read" in _step(path, "namespace").detail


def test_a_non_numeric_stale_after_s_is_not_connected_and_does_not_raise(tmp_path):
    path = _path(Config((_broker(stale="abc"),)), tmp_path)
    assert _step(path, "connect").state == STATE_NEXT


# --- front-end review findings --------------------------------------------------


def test_the_cli_records_what_the_audit_can_vouch_for(tmp_path, monkeypatch):
    """The record must carry the broker, the naming standard and the cap the capture
    really ran with — `--max-msgs 9999` is clamped to 500 by the collector, and
    recording 9999 would make a capture that stopped at 500 look complete."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_UNS_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    _patched_live_audit(monkeypatch)
    from iaiops.cli._root import app

    result = runner.invoke(
        app,
        [
            "mqtt",
            "uns-live-audit",
            "--endpoint",
            "uns-1",
            "--duration-s",
            "1",
            "--root",
            "plant",
            "--min-segments",
            "3",
            "--max-msgs",
            "9999",
        ],
    )
    assert result.exit_code == 0, result.output
    record = load_uns_audit("uns-1")
    assert record is not None and not record.error, record
    assert record.allowed_roots == ("plant",) and record.min_segments == 3
    assert record.max_msgs == 500
    assert record.duration_s == 1
    assert record.broker and record.broker != ":0", record.broker


def test_a_narrow_mcp_audit_cannot_overwrite_a_finding_into_b1(tmp_path, monkeypatch):
    """Reproduced on a real broker: a whole-tree audit said minor, then a clean
    audit of ONE topic replaced it and onboard said B1."""
    from iaiops.connectors.sparkplug import live
    from mcp_server.tools import sparkplug_tools

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_UNS_CONFIG)
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    monkeypatch.setattr(
        live,
        "uns_live_audit",
        lambda target, topic="#", *a, **k: _audit("clean", endpoint=target.name, topic=topic),
    )
    out = sparkplug_tools.uns_live_audit(
        endpoint="uns-1",
        topic="plant/line1/temp",
        duration_s=1,
        allowed_roots=["plant"],
        min_segments=2,
    )
    assert out.get("stored_for_onboard") is True, out
    path = assess_path(db_path=tmp_path / "n.db", track="uns")
    assert "B1 — " not in path.track_detail, path.track_detail
    # Refused for the reason under test, not for a short window or another gap.
    namespace = next(s for s in path.steps if s.key == "namespace")
    assert "does not cover" in namespace.detail, namespace.detail


def test_an_mcp_caller_with_a_bad_track_is_not_sent_to_doctor(tmp_path, monkeypatch):
    from mcp_server.tools import overview_tools

    cfg = tmp_path / "config.yaml"
    cfg.write_text("endpoints: []\n")
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    out = overview_tools.onboarding_status(db=str(tmp_path / "n.db"), track="broker")
    assert "Unknown track" in out.get("error", ""), out
    assert "doctor" not in out.get("hint", ""), out


def test_the_cli_prints_the_question_once(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("endpoints: []\n")
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    from iaiops.cli._root import app

    result = runner.invoke(app, ["onboard", "status", "--db", str(tmp_path / "n.db")])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert flat.count("Nothing is configured") == 1, result.output
    assert flat.count("--track devices") == 1 and flat.count("--track uns") == 1


def test_an_audit_stored_without_its_message_cap_cannot_make_b1(tmp_path):
    """Survived mutation: an unrecorded cap was read as "the capture was whole".
    Nothing says it did not stop at the collector's limit, so it cannot vouch."""
    broker = _broker()
    _save(_audit("clean"), broker, tmp_path, cap=0)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail, path.track_detail
    assert "did not record its message cap" in _step(path, "namespace").detail


# --- second re-review findings ---------------------------------------------------


def test_findings_over_the_whole_broker_do_not_make_a_narrower_endpoint_b2(tmp_path):
    """A `#` audit found `Test/x` and `scratch`; the endpoint subscribes to `plant/#`."""
    broker = _broker(topic="plant/#")
    _save(_audit("sprawling", findings=8, topic="#"), broker, tmp_path)
    path = _path(Config((broker,)), tmp_path)
    assert "B2 — " not in path.track_detail, path.track_detail
    assert "whole broker" in _step(path, "namespace").detail


def test_b2_on_plain_mqtt_does_not_prescribe_a_schema_baseline_in_the_step(tmp_path):
    broker = _broker(topic="plant/#")
    _save(_audit("sprawling", findings=8, topic="plant/#"), broker, tmp_path)
    path = _path(Config((broker,)), tmp_path)
    assert "B2 — " in path.track_detail, path.track_detail
    assert "baseline" not in _step(path, "namespace").detail


def test_a_capture_shorter_than_the_publish_interval_cannot_make_b1(tmp_path):
    """Reproduced: points every 20 s, stale_after_s 60, a 2 s capture read clean."""
    broker = _broker(stale=60.0)
    _save(_audit("clean"), broker, tmp_path, duration=2)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail, path.track_detail
    namespace = _step(path, "namespace")
    assert "listened 2s" in namespace.detail
    assert "--duration-s 60" in namespace.command


def _stored_doc(tmp_path, **changes):
    import json

    broker = _broker()
    _save(_audit("clean"), broker, tmp_path)
    target = audit_file("uns-1", tmp_path / "audits")
    doc = json.loads(target.read_text())
    for key, value in changes.items():
        if value is _DROP:
            doc.pop(key, None)
        else:
            doc[key] = value
    target.write_text(json.dumps(doc))
    return broker


_DROP = object()


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 999},
        {"version": _DROP},
        {"verdict": "bogus"},
        {"verdict": "Clean"},
        {"sprawl_findings": 7},
        {"allowed_roots": [""]},
        {"max_msgs": 0, "capture_capped": False},
        {"observed_messages": 500, "max_msgs": 500, "capture_capped": False},
    ],
)
def test_a_hand_edited_record_cannot_grant_b1(tmp_path, changes):
    """Each of these was loaded as B1 (or `bogus` as B2) — values save never writes."""
    broker = _stored_doc(tmp_path, **changes)
    path = _path(Config((broker,)), tmp_path)
    assert "B1 — " not in path.track_detail, (changes, path.track_detail)
    assert "B2 — " not in path.track_detail, (changes, path.track_detail)


def test_save_refuses_a_verdict_that_does_not_match_its_findings(tmp_path):
    assert _save(_audit("clean", findings=3), _broker(), tmp_path) is None


def test_a_broker_endpoint_with_no_host_is_not_connected(tmp_path):
    path = _path(Config((_broker(host=""),)), tmp_path)
    connect = _step(path, "connect")
    assert connect.state == STATE_NEXT and "no host" in connect.detail


def test_an_empty_journey_is_not_blamed_on_the_build(tmp_path):
    path = _path(Config((_broker(),)), tmp_path, track="devices")
    collect = _step(path, "collect")
    assert "this build" not in collect.detail, collect.detail


def test_the_oldest_audit_is_the_oldest_instant_not_the_smallest_string():
    """As text `…T20:00+09:00` sorts after `…T12:00+00:00`; as a time it is an hour
    earlier (11:00 UTC). The journey line must report the older instant."""
    from datetime import datetime, timedelta, timezone

    from iaiops.core.onboard.uns_steps import _uns_subtrack
    from iaiops.core.sink.uns_audit_store import UnsAuditRecord

    def record(name, stamp):
        return UnsAuditRecord(
            endpoint=name,
            verdict="clean",
            topic_count=12,
            observed_messages=40,
            audited_at=stamp.isoformat(timespec="seconds"),
            topic_filter="plant/#",
            broker="10.0.0.5:1883",
            allowed_roots=("plant",),
            min_segments=2,
            max_msgs=500,
            capture_capped=False,
            duration_s=30,
        )

    east = datetime(2026, 1, 2, 20, 0, tzinfo=timezone(timedelta(hours=9)))
    west = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    assert east.isoformat() > west.isoformat() and east < west
    a, b = _broker(name="a"), _broker(name="b")
    sub, text, _ = _uns_subtrack(
        (a, b), {"a": record("a", east), "b": record("b", west)}, west + timedelta(minutes=30)
    )
    assert sub == "B1", text
    assert "oldest audit 1 h ago" in text, text
