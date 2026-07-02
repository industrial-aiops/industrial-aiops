"""Tests for audit-log forwarding (read-only SIEM egress).

A fake sink collects JSON lines in-memory so the cursor dedupe, JSON shape, and
sink construction/validation are exercised without opening a real socket.
"""

from __future__ import annotations

import json

import pytest

from iaiops.core.governance.audit import AuditEngine
from iaiops.core.governance.forward import (
    HttpSink,
    SyslogUDPSink,
    build_sink,
    forward_audit,
    forward_follow,
    read_cursor,
    row_to_line,
)


class _FakeSink:
    """Collect emitted JSON lines; optionally fail after N sends."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.lines: list[str] = []
        self.closed = False
        self._fail_after = fail_after

    def send(self, line: str) -> None:
        if self._fail_after is not None and len(self.lines) >= self._fail_after:
            raise RuntimeError("collector unreachable")
        self.lines.append(line)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def engine(tmp_path):
    """A fresh AuditEngine backed by a throwaway DB."""
    return AuditEngine(tmp_path / "audit.db")


def _seed(engine: AuditEngine, n: int) -> None:
    for i in range(n):
        engine.log(skill="opcua", tool="read", params={"i": i}, result={"v": i}, status="ok")


@pytest.mark.unit
def test_forward_emits_json_line_per_row(tmp_path, engine):
    _seed(engine, 3)
    sink = _FakeSink()
    cursor = tmp_path / "cur"
    out = forward_audit(sink, engine=engine, cursor_path=cursor)
    assert out["forwarded"] == 3
    assert len(sink.lines) == 3
    # Each line is valid JSON with the audit fields; params re-parsed to nested JSON.
    first = json.loads(sink.lines[0])
    assert first["skill"] == "opcua" and first["tool"] == "read"
    assert first["params"] == {"i": 0}


@pytest.mark.unit
def test_cursor_dedupe_rerun_forwards_only_new(tmp_path, engine):
    _seed(engine, 2)
    cursor = tmp_path / "cur"
    first = forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)
    assert first["forwarded"] == 2

    # Re-run with no new rows: nothing forwarded.
    again = _FakeSink()
    out = forward_audit(again, engine=engine, cursor_path=cursor)
    assert out["forwarded"] == 0
    assert again.lines == []

    # Add rows: only the new ones go out.
    _seed(engine, 3)
    third = _FakeSink()
    out = forward_audit(third, engine=engine, cursor_path=cursor)
    assert out["forwarded"] == 3
    assert len(third.lines) == 3
    assert out["from_cursor"] == 2 and out["cursor"] == 5


@pytest.mark.unit
def test_cursor_not_advanced_when_send_fails(tmp_path, engine):
    _seed(engine, 3)
    cursor = tmp_path / "cur"
    sink = _FakeSink(fail_after=1)
    with pytest.raises(RuntimeError):
        forward_audit(sink, engine=engine, cursor_path=cursor)
    # First row delivered, but cursor never persisted → clean retry re-sends all.
    assert read_cursor(cursor) == 0
    retry = _FakeSink()
    out = forward_audit(retry, engine=engine, cursor_path=cursor)
    assert out["forwarded"] == 3


@pytest.mark.unit
def test_since_filter_first_run(tmp_path, engine):
    _seed(engine, 2)
    # Future floor → nothing matches.
    out = forward_audit(
        _FakeSink(), engine=engine, cursor_path=tmp_path / "c", since="2999-01-01T00:00:00+00:00"
    )
    assert out["forwarded"] == 0


@pytest.mark.unit
def test_follow_bounded_cycles(tmp_path, engine):
    _seed(engine, 2)
    sink = _FakeSink()
    out = forward_follow(sink, engine=engine, cursor_path=tmp_path / "c", max_cycles=1)
    assert out["cycles"] == 1
    assert out["forwarded"] == 2
    assert len(sink.lines) == 2


@pytest.mark.unit
def test_row_to_line_leaves_non_json_text_raw():
    line = row_to_line({"id": 1, "params": "not-json{", "result": "{}"})
    parsed = json.loads(line)
    assert parsed["params"] == "not-json{"  # untouched
    assert parsed["result"] == {}  # valid JSON re-parsed


@pytest.mark.unit
def test_build_sink_validates_kind():
    with pytest.raises(ValueError, match="Unknown sink"):
        build_sink("kafka", host="localhost")


@pytest.mark.unit
def test_build_sink_syslog_requires_host():
    with pytest.raises(ValueError, match="requires --host"):
        build_sink("syslog", host="")


@pytest.mark.unit
def test_build_sink_http_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http/https"):
        build_sink("http", host="ftp://collector/ingest")


@pytest.mark.unit
def test_build_sink_http_builds_url():
    sink = build_sink("http", host="siem.local", port=8088, path="/ingest")
    assert isinstance(sink, HttpSink)
    assert sink._url == "http://siem.local:8088/ingest"


@pytest.mark.unit
def test_build_sink_syslog_default_port():
    sink = build_sink("syslog", host="10.0.0.9")
    assert isinstance(sink, SyslogUDPSink)
    assert sink._addr == ("10.0.0.9", 514)
    sink.close()
