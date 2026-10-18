"""A polled OPC UA value that did not change is still an observation.

The collect runner skips a read whose source timestamp equals the last one it
wrote: "same publish, polled again". That is right for MQTT, where the stamp
identifies a publish and a re-read of the last-value cache is not new. It is
wrong for OPC UA, where ``SourceTimestamp`` is when the value last CHANGED: every
poll of a steady state was dropped. Measured (2026-10-18): 49 polls over 6 s
of a line that ran, then stopped, stored 2 samples while the run reported 100%
coverage — and `oee measure` then had nothing to measure. Over a longer run the
bias has a direction: a state that lasts longer than a few change-intervals is
the one that turns into blind time, and the long stops are the losses.

So an OPC UA read is stamped when it was polled. What a server that lost its
device does instead is say so in the status — the four "not observed"
Uncertain codes — and those are gaps, never values.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
from pathlib import Path

import pytest

from iaiops.connectors.opcua.ops import opcua_session, read_observation
from iaiops.core.brain.oee_measure import measure_availability
from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.reader import (
    polls_are_fresh,
    session_builder_for,
    session_read_for,
)
from iaiops.core.collect.runner import run_collection
from iaiops.core.runtime.config import MonitorTag, TargetConfig
from iaiops.core.runtime.session_factory import OTNoReadingError

RUNNING, STOPPED = 6, 2
INTERVAL_MS = 100


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server():
    from asyncua import ua
    from asyncua.sync import Server

    url = f"opc.tcp://127.0.0.1:{_free_port()}/steady"
    srv = Server()
    srv.set_endpoint(url)
    idx = srv.register_namespace("http://vendor.example/line")
    state = srv.nodes.objects.add_variable(idx, "State", ua.Variant(RUNNING, ua.VariantType.UInt32))
    srv.start()
    try:
        yield {"url": url, "state": state, "ref": state.nodeid.to_string()}
    finally:
        srv.stop()


def _target(url: str) -> TargetConfig:
    return TargetConfig(name="line1", protocol="opcua", endpoint_url=url)


def _samples(db: Path) -> list[dict]:
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        if not conn.execute("SELECT name FROM sqlite_master WHERE name='samples'").fetchall():
            return []
        rows = conn.execute("SELECT ts, value FROM samples ORDER BY ts").fetchall()
    return [{"ts": ts, "value": value} for ts, value in rows]


def _collect(url: str, ref: str, db: Path, iterations: int):
    plan = CollectionPlan(endpoint="line1", tags=(ref,), duration_s=60, interval_ms=INTERVAL_MS)
    return run_collection(
        plan,
        _target(url),
        reader=session_read_for("opcua"),
        db_path=db,
        max_iterations=iterations,
        session_builder=session_builder_for("opcua"),
        fresh_each_read=polls_are_fresh("opcua"),
    )


# ── which protocols ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_opcua_polls_are_fresh_and_mqtt_publishes_are_not():
    assert polls_are_fresh("opcua") is True
    # MQTT's stamp identifies a publish: re-reading the cache is NOT new.
    assert polls_are_fresh("mqtt") is False
    assert polls_are_fresh("modbus") is False  # states no timestamp; nothing to dedupe
    assert polls_are_fresh("nonsense") is False


@pytest.mark.unit
def test_a_fresh_reader_stamps_each_read_with_the_poll_not_the_change(tmp_path):
    """Same source stamp every read: all written, each at its own poll time."""
    plan = CollectionPlan(endpoint="x", tags=("a",), duration_s=60, interval_ms=50)
    result = run_collection(
        plan,
        target=TargetConfig(name="x", protocol="opcua", endpoint_url="opc.tcp://x:1"),
        reader=lambda _s, _r: (RUNNING, "2026-01-01T00:00:00+00:00"),
        db_path=tmp_path / "s.db",
        max_iterations=5,
        fresh_each_read=True,
    )
    assert (result.samples_written, result.repeats) == (5, 0)
    stamps = [row["ts"] for row in _samples(tmp_path / "s.db")]
    assert len(set(stamps)) == 5
    assert not any(ts.startswith("2026-01-01") for ts in stamps)


# ── through a real server ────────────────────────────────────────────────────


@pytest.mark.integration
def test_steady_running_then_steady_stopped_is_measured(server, tmp_path):
    """Each state written ONCE on the server, as a PLC does; polled for 1.5 s each."""
    from asyncua import ua

    flip = threading.Timer(
        1.5, lambda: server["state"].write_value(ua.Variant(STOPPED, ua.VariantType.UInt32))
    )
    flip.start()
    try:
        result = _collect(server["url"], server["ref"], tmp_path / "s.db", 30)
    finally:
        flip.join()

    assert result.repeats == 0
    samples = _samples(tmp_path / "s.db")
    assert len(samples) == result.samples_written >= 25
    tag = MonitorTag(ref=server["ref"], role="run_state", running_when=(RUNNING,))
    out = measure_availability(samples, tag)
    assert out["status"] == "ok", out
    assert out["unknown_s"] < 0.5, out
    assert out["stopped_s"] > 0.8, out
    assert 0.3 < out["availability"] < 0.7, out


@pytest.mark.integration
@pytest.mark.parametrize(
    "code",
    [
        "UncertainLastUsableValue",
        "UncertainNoCommunicationLastUsableValue",
        "UncertainSubstituteValue",
        "UncertainInitialValue",
    ],
)
def test_a_value_the_server_did_not_observe_is_a_gap(server, tmp_path, code):
    """Once polls count as observations, the server's own 'stale' flag is the guard."""
    from asyncua import ua

    server["state"].write_value(
        ua.DataValue(
            Value=ua.Variant(RUNNING, ua.VariantType.UInt32),
            StatusCode=ua.StatusCode(getattr(ua.StatusCodes, code)),
        )
    )
    with opcua_session(_target(server["url"])) as client:
        with pytest.raises(OTNoReadingError, match=code):
            read_observation(client, server["ref"])
    result = _collect(server["url"], server["ref"], tmp_path / "s.db", 3)
    assert result.samples_written == 0 and result.gaps
    assert _samples(tmp_path / "s.db") == []


@pytest.mark.integration
def test_an_uncertain_measurement_is_still_a_value(server):
    """Uncertain about ACCURACY is not uncertain about WHEN — the value was observed."""
    from asyncua import ua

    server["state"].write_value(
        ua.DataValue(
            Value=ua.Variant(RUNNING, ua.VariantType.UInt32),
            StatusCode=ua.StatusCode(ua.StatusCodes.UncertainEngineeringUnitsExceeded),
        )
    )
    with opcua_session(_target(server["url"])) as client:
        value, _ = read_observation(client, server["ref"])
    assert value == RUNNING


# ── the CLI wires it ─────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ({"name": "u", "protocol": "opcua", "endpoint_url": "opc.tcp://h:4840"}, True),
        ({"name": "u", "protocol": "modbus", "host": "h"}, False),
    ],
)
def test_collect_run_passes_the_protocols_freshness(tmp_path, monkeypatch, target, expected):
    import yaml
    from typer.testing import CliRunner

    from iaiops.cli.collect import collect_app
    from iaiops.core.collect.runner import RunResult

    ref = "ns=2;i=1" if target["protocol"] == "opcua" else "40001"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"targets": [{**target, "tags": [{"ref": ref}]}]}), "utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("IAIOPS_CONFIG", str(path))
    monkeypatch.setattr(
        "iaiops.core.collect.session.session_path",
        lambda run_id, base_dir=None: tmp_path / f"{run_id}.json",
    )
    seen: dict = {}

    def fake_run(plan, **kwargs):
        seen.update(kwargs)
        return RunResult(plan=plan, samples_written=0, attempted=0)

    monkeypatch.setattr("iaiops.core.collect.runner.run_collection", fake_run)
    result = CliRunner().invoke(collect_app, ["run", "u", "--duration", "1m", "--db", "x.db"])
    assert "fresh_each_read" in seen, result.output
    assert seen["fresh_each_read"] is expected
