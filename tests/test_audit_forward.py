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
def test_partial_failure_persists_delivered_rows_at_least_once(tmp_path, engine):
    _seed(engine, 3)
    cursor = tmp_path / "cur"
    sink = _FakeSink(fail_after=1)  # row 1 sends, row 2's send raises
    with pytest.raises(RuntimeError):
        forward_audit(sink, engine=engine, cursor_path=cursor)
    assert sink.lines and len(sink.lines) == 1  # row 1 was delivered
    # At-least-once: the delivered row's id is persisted so retry does NOT re-send it.
    assert read_cursor(cursor).id == 1
    retry = _FakeSink()
    out = forward_audit(retry, engine=engine, cursor_path=cursor)
    # Retry resumes after the last delivered row: re-sends the failing row (2) + rest (3),
    # never the already-delivered row 1.
    assert out["forwarded"] == 2
    assert out["from_cursor"] == 1 and out["cursor"] == 3


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
    # Bare hosts default to https (M-5 hardening); explicit http:// still works.
    assert sink._url == "https://siem.local:8088/ingest"


@pytest.mark.unit
def test_build_sink_syslog_default_port():
    sink = build_sink("syslog", host="10.0.0.9")
    assert isinstance(sink, SyslogUDPSink)
    assert sink._addr == ("10.0.0.9", 514)
    sink.close()


# ── syslog datagram truncation must keep the record valid JSON ────────────────


class _FakeSocket:
    """Capture sendto payloads without touching the network."""

    def __init__(self) -> None:
        self.datagrams: list[bytes] = []

    def sendto(self, payload: bytes, addr) -> None:
        self.datagrams.append(payload)

    def close(self) -> None:
        pass


def _capturing_syslog_sink() -> tuple[SyslogUDPSink, _FakeSocket]:
    sink = SyslogUDPSink("127.0.0.1", 514)
    sink._sock.close()
    fake = _FakeSocket()
    sink._sock = fake
    return sink, fake


def _record_from(payload: bytes) -> dict:
    body = payload.decode("utf-8").split("iaiops-audit: ", 1)[1]
    return json.loads(body)  # raises if truncation corrupted the JSON


@pytest.mark.unit
def test_syslog_small_line_sent_verbatim():
    sink, fake = _capturing_syslog_sink()
    line = json.dumps({"id": 1, "tool": "read", "params": {"i": 0}})
    sink.send(line)
    record = _record_from(fake.datagrams[0])
    assert record == {"id": 1, "tool": "read", "params": {"i": 0}}
    assert "_truncated" not in record


@pytest.mark.unit
def test_syslog_oversized_line_shrinks_to_valid_json():
    sink, fake = _capturing_syslog_sink()
    line = json.dumps(
        {
            "id": 7,
            "tool": "write_tag",
            "status": "ok",
            "params": {"blob": "A" * 70000},
            "result": {"ok": True},
        }
    )
    sink.send(line)
    payload = fake.datagrams[0]
    assert len(payload) <= 65000
    record = _record_from(payload)  # must still parse as JSON
    assert record["_truncated"] is True
    assert record["id"] == 7 and record["tool"] == "write_tag"
    assert "A" * 100 not in json.dumps(record)  # bulk params dropped


@pytest.mark.unit
def test_syslog_oversized_result_also_shrinks():
    sink, fake = _capturing_syslog_sink()
    line = json.dumps({"id": 8, "tool": "read", "params": {}, "result": "B" * 70000})
    sink.send(line)
    payload = fake.datagrams[0]
    assert len(payload) <= 65000
    record = _record_from(payload)
    assert record["_truncated"] is True and record["id"] == 8


# ── rotation: the cursor must survive the DB restarting ids at 1 ─────────────


def _rotate(engine: AuditEngine, monkeypatch, *, year: int = 2030) -> None:
    """Force one rotation now, regardless of the real 100 MB threshold.

    ``year`` fixes the archive's timestamped name, so two rotations in one test
    get two archives instead of colliding within the same second.
    """
    import iaiops.core.governance.audit as audit_mod

    real = audit_mod.datetime

    class _Clock(real):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return real(year, 1, 1, tzinfo=tz)

    monkeypatch.setattr(audit_mod, "datetime", _Clock)
    monkeypatch.setattr(audit_mod, "_MAX_DB_SIZE_BYTES", 1)
    engine._maybe_rotate()
    monkeypatch.undo()


def _forwarded_params(sink: _FakeSink) -> list[int]:
    return [json.loads(line)["params"]["i"] for line in sink.lines]


def _seed_from(engine: AuditEngine, start: int, n: int) -> None:
    for i in range(start, start + n):
        engine.log(skill="opcua", tool="read", params={"i": i}, result={}, status="ok")


@pytest.mark.unit
def test_rows_after_rotation_are_all_forwarded_exactly_once(tmp_path, engine, monkeypatch):
    """Ids restart at 1 after a rotation; an id cursor would skip rows 1..old."""
    cursor = tmp_path / "cur"
    sink = _FakeSink()
    _seed_from(engine, 0, 5)
    forward_audit(sink, engine=engine, cursor_path=cursor)
    _seed_from(engine, 5, 2)  # written after the forward, before the rotation
    _rotate(engine, monkeypatch)
    _seed_from(engine, 7, 3)  # new file: ids 1..3, all below the old cursor (5)
    forward_audit(sink, engine=engine, cursor_path=cursor)
    forward_audit(sink, engine=engine, cursor_path=cursor)  # idempotent re-run
    assert _forwarded_params(sink) == list(range(10))


@pytest.mark.unit
def test_rotation_survived_across_several_archives(tmp_path, engine, monkeypatch):
    cursor = tmp_path / "cur"
    sink = _FakeSink()
    _seed_from(engine, 0, 2)
    forward_audit(sink, engine=engine, cursor_path=cursor)
    _seed_from(engine, 2, 2)
    _rotate(engine, monkeypatch, year=2030)
    _seed_from(engine, 4, 2)
    _rotate(engine, monkeypatch, year=2031)
    _seed_from(engine, 6, 1)
    forward_audit(sink, engine=engine, cursor_path=cursor)
    assert _forwarded_params(sink) == list(range(7))


@pytest.mark.unit
def test_batch_limit_resumes_inside_an_archive(tmp_path, engine, monkeypatch):
    cursor = tmp_path / "cur"
    sink = _FakeSink()
    _seed_from(engine, 0, 4)
    _rotate(engine, monkeypatch)
    _seed_from(engine, 4, 3)
    for _ in range(5):
        forward_audit(sink, engine=engine, cursor_path=cursor, limit=2)
    assert _forwarded_params(sink) == list(range(7))


@pytest.mark.unit
def test_first_run_includes_archived_rows(tmp_path, engine, monkeypatch):
    _seed_from(engine, 0, 2)
    _rotate(engine, monkeypatch)
    _seed_from(engine, 2, 2)
    sink = _FakeSink()
    forward_audit(sink, engine=engine, cursor_path=tmp_path / "cur")
    assert _forwarded_params(sink) == [0, 1, 2, 3]


@pytest.mark.unit
def test_cursor_row_gone_with_deleted_archive_refuses(tmp_path, engine, monkeypatch):
    """Archives past the retention limit are deleted: refuse, don't guess."""
    from iaiops.core.governance.forward import CursorLost

    cursor = tmp_path / "cur"
    _seed_from(engine, 0, 3)
    forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)
    _rotate(engine, monkeypatch)
    for archive in tmp_path.glob("audit.*.db"):
        archive.unlink()
    _seed_from(engine, 3, 5)
    sink = _FakeSink()
    with pytest.raises(CursorLost, match="cannot be placed"):
        forward_audit(sink, engine=engine, cursor_path=cursor)
    assert sink.lines == []


@pytest.mark.unit
def test_cursor_whose_row_was_replaced_refuses(tmp_path, engine, monkeypatch):
    """Same id, different row (new file, no archive): never treat it as placed."""
    from iaiops.core.governance.forward import CursorLost

    cursor = tmp_path / "cur"
    _seed_from(engine, 0, 2)
    forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)
    _rotate(engine, monkeypatch)
    for archive in tmp_path.glob("audit.*.db"):
        archive.unlink()
    _seed_from(engine, 2, 3)  # id 2 exists again, but it is a different row
    with pytest.raises(CursorLost):
        forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)


@pytest.mark.unit
def test_legacy_int_cursor_honoured_only_when_no_rotation_happened(tmp_path, engine, monkeypatch):
    from iaiops.core.governance.forward import CursorLost

    cursor = tmp_path / "cur"
    _seed_from(engine, 0, 4)
    cursor.write_text("2", "utf-8")  # pre-0.29 cursor format
    sink = _FakeSink()
    forward_audit(sink, engine=engine, cursor_path=cursor)
    assert _forwarded_params(sink) == [2, 3]

    cursor.write_text("2", "utf-8")
    _rotate(engine, monkeypatch)
    _seed_from(engine, 4, 3)
    with pytest.raises(CursorLost, match="rotat"):
        forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)


@pytest.mark.unit
def test_corrupt_cursor_refuses(tmp_path, engine):
    from iaiops.core.governance.forward import CursorLost

    cursor = tmp_path / "cur"
    _seed_from(engine, 0, 2)
    cursor.write_text("{not json", "utf-8")
    with pytest.raises(CursorLost):
        forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)


def _set_column(db, row_id: int, column: str, value: str) -> None:
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        # ``column`` is a test literal, never input.
        conn.execute(f"UPDATE audit_log SET {column} = ? WHERE id = ?", (value, row_id))  # nosec B608
        conn.commit()
    finally:
        conn.close()


@pytest.mark.unit
@pytest.mark.parametrize("column", ["ts", "row_hash"])
def test_each_identity_field_is_checked_when_placing(tmp_path, engine, column):
    """A row matching on id but differing on ts *or* row_hash is not the cursor row.

    ``ts`` is the only identity an unchained (pre-migration) row has, and
    ``row_hash`` the one that changes when anything else differs.
    """
    from iaiops.core.governance.forward import CursorLost

    cursor = tmp_path / "cur"
    _seed_from(engine, 0, 2)
    forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)
    _set_column(engine.path, 2, column, "something-else")
    with pytest.raises(CursorLost):
        forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)


@pytest.mark.unit
def test_legacy_int_cursor_beyond_the_live_db_refuses(tmp_path, engine):
    from iaiops.core.governance.forward import CursorLost

    cursor = tmp_path / "cur"
    _seed_from(engine, 0, 3)
    cursor.write_text("99", "utf-8")
    with pytest.raises(CursorLost, match="not in the live"):
        forward_audit(_FakeSink(), engine=engine, cursor_path=cursor)
