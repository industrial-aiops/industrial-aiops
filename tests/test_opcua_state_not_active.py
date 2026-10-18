"""OPC UA collection: a Bad status is never a value, except Bad_StateNotActive.

Before this, the collector read OPC UA through ``_read_one``, which reports any
failure as an ``{"error"}`` descriptor, and took ``value`` off it: a rejected node
and a dead connection were both stored as an empty sample at 100% coverage. On a
run-state tag that empty sample means "not running", so blind time was measured
as downtime, and a dropped session was never reconnected because nothing raised.

Now the outcomes stay apart, and each is pinned against a REAL in-process asyncua
server, through the same reader ``iaiops collect run`` uses:

* Bad_StateNotActive (OPC 10000-16 §4.4.2 — an inactive sub-state machine) is a
  definite "not running" sample, session kept;
* any other Bad status is a gap, session kept;
* a lost connection is a gap AND a reconnect.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from iaiops.connectors.opcua.ops import STATE_NOT_ACTIVE, opcua_session, read_observation
from iaiops.core.brain.oee_measure import measure_availability
from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.reader import read_point, session_builder_for, session_read_for
from iaiops.core.collect.runner import run_collection
from iaiops.core.runtime.config import MonitorTag, TargetConfig
from iaiops.core.runtime.session_factory import OTNoReadingError

EXECUTE = 6
INTERVAL_MS = 100


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _not_active():
    from asyncua import ua

    return ua.DataValue(StatusCode=ua.StatusCode(ua.StatusCodes.BadStateNotActive))


def _start_server():
    from asyncua import ua
    from asyncua.sync import Server

    url = f"opc.tcp://127.0.0.1:{_free_port()}/state"
    srv = Server()
    srv.set_endpoint(url)
    idx = srv.register_namespace("http://vendor.example/line")
    line = srv.nodes.objects.add_object(idx, "Line")
    number = line.add_variable(idx, "ExecuteNumber", ua.Variant(EXECUTE, ua.VariantType.UInt32))
    rejected = line.add_variable(idx, "Rejected", ua.Variant(0, ua.VariantType.UInt32))
    rejected.write_value(ua.DataValue(StatusCode=ua.StatusCode(ua.StatusCodes.BadDeviceFailure)))
    srv.start()
    return srv, url, number, rejected


@pytest.fixture
def server():
    srv, url, number, rejected = _start_server()
    stopped = {"done": False}
    try:
        yield {
            "srv": srv,
            "url": url,
            "number": number,
            "number_id": number.nodeid.to_string(),
            "rejected_id": rejected.nodeid.to_string(),
            "stopped": stopped,
        }
    finally:
        if not stopped["done"]:
            srv.stop()


def _target(url: str) -> TargetConfig:
    return TargetConfig(name="line1", protocol="opcua", endpoint_url=url)


def _collect(target, ref: str, db: Path, iterations: int, session: bool = True):
    plan = CollectionPlan(endpoint="line1", tags=(ref,), duration_s=60, interval_ms=INTERVAL_MS)
    reader = session_read_for("opcua") if session else read_point
    return run_collection(
        plan,
        target,
        reader=reader,
        db_path=db,
        max_iterations=iterations,
        session_builder=session_builder_for("opcua") if session else None,
    )


def _samples(db: Path) -> list[dict]:
    """Stored samples; none when nothing was ever written (the table is created on write)."""
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE name = 'samples'").fetchall()
        if not tables:
            return []
        rows = conn.execute("SELECT ts, value FROM samples ORDER BY ts").fetchall()
    return [{"ts": ts, "value": value} for ts, value in rows]


# ── the read itself ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_state_not_active_reads_as_a_definite_value(server):
    server["number"].write_value(_not_active())
    with opcua_session(_target(server["url"])) as client:
        value, _ = read_observation(client, server["number_id"])
    assert value == STATE_NOT_ACTIVE
    tag = MonitorTag(ref=server["number_id"], role="run_state", running_when=(EXECUTE,))
    assert tag.is_running(value) is False


@pytest.mark.integration
def test_other_bad_statuses_are_no_reading_not_a_value(server):
    with opcua_session(_target(server["url"])) as client:
        with pytest.raises(OTNoReadingError, match="BadDeviceFailure"):
            read_observation(client, server["rejected_id"])
        with pytest.raises(OTNoReadingError, match="BadNodeIdUnknown"):
            read_observation(client, "ns=2;i=99999")
        with pytest.raises(OTNoReadingError):
            read_observation(client, "not a node id")


@pytest.mark.integration
def test_a_good_read_is_unchanged(server):
    with opcua_session(_target(server["url"])) as client:
        value, stamp = read_observation(client, server["number_id"])
    assert value == EXECUTE and stamp


# ── through the collector ────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("session", [True, False], ids=["session", "one-shot"])
def test_a_rejected_node_is_a_gap_never_an_empty_sample(server, tmp_path, session):
    """The old path stored ``""`` here with 100% coverage — downtime out of nothing."""
    result = _collect(_target(server["url"]), server["rejected_id"], tmp_path / "s.db", 3, session)
    assert result.samples_written == 0
    assert result.coverage_pct == 0.0
    assert result.gaps and "BadDeviceFailure" in result.gaps[0]["reason"]
    assert _samples(tmp_path / "s.db") == []


@pytest.mark.integration
def test_a_rejected_node_keeps_the_session(server, tmp_path, monkeypatch):
    """No teardown per tick: a device that is answering is not hammered with reconnects."""
    opened = []
    builder = session_builder_for("opcua")

    def counting(target):
        opened.append(1)
        return builder(target)

    plan = CollectionPlan(
        endpoint="line1", tags=(server["rejected_id"],), duration_s=60, interval_ms=INTERVAL_MS
    )
    run_collection(
        plan,
        _target(server["url"]),
        reader=session_read_for("opcua"),
        db_path=tmp_path / "s.db",
        max_iterations=4,
        session_builder=counting,
    )
    assert len(opened) == 1


@pytest.mark.integration
def test_a_lost_connection_is_a_gap_and_a_reconnect_not_downtime(server, tmp_path):
    """Before, `_read_one` swallowed the transport error: '' samples, no reconnect."""
    srv = server["srv"]

    def kill() -> None:
        srv.stop()
        server["stopped"]["done"] = True

    timer = threading.Timer(0.5, kill)
    timer.start()
    try:
        result = _collect(_target(server["url"]), server["number_id"], tmp_path / "s.db", 12)
    finally:
        timer.join()
    values = [row["value"] for row in _samples(tmp_path / "s.db")]
    assert "" not in values and None not in values
    assert result.gaps, "a dead server must leave a blind window"
    assert result.coverage_pct < 100.0


@pytest.mark.integration
def test_a_stopped_sub_state_machine_measures_as_stopped(server, tmp_path):
    """Running (Execute = 6) for the first half, inactive sub-state for the second.

    A server thread rewrites the value every scan, so each poll is a fresh
    observation. Availability must come out near one half with the stopped half
    counted as STOPPED — not as blind time, which would put it near 100%.
    """
    from asyncua import ua

    number = server["number"]
    halt = threading.Event()
    stop_after = time.monotonic() + 1.5

    def scan() -> None:
        while not halt.is_set():
            if time.monotonic() < stop_after:
                number.write_value(ua.Variant(EXECUTE, ua.VariantType.UInt32))
            else:
                number.write_value(_not_active())
            time.sleep(0.02)

    scanner = threading.Thread(target=scan, daemon=True)
    scanner.start()
    try:
        result = _collect(_target(server["url"]), server["number_id"], tmp_path / "s.db", 30)
    finally:
        halt.set()
        scanner.join()

    assert result.gaps == ()
    samples = _samples(tmp_path / "s.db")
    values = {row["value"] for row in samples}
    assert values == {float(EXECUTE), STATE_NOT_ACTIVE}
    tag = MonitorTag(ref=server["number_id"], role="run_state", running_when=(EXECUTE,))
    out = measure_availability(samples, tag)
    assert out["status"] == "ok", out
    assert out["stopped_s"] > 0.8
    assert out["unknown_s"] < 0.5
    assert 0.3 < out["availability"] < 0.7, out
