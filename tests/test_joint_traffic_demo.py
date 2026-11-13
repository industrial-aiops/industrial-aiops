"""Exercise the actual fixture sockets, governed collector, evidence and cleanup."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import socket
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "demo/joint-traffic/joint_demo.py"
PYTHON = ROOT / ".venv/bin/python"
spec = importlib.util.spec_from_file_location("joint_demo", SCRIPT)
joint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(joint)


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    output = tmp_path_factory.mktemp("joint-demo") / "run"
    # Poison inherited app configuration: the collector must still use its own fixture.
    env = dict(os.environ, IAIOPS_CONFIG="/not/a/real/config.yaml", IAIOPS_HOME="/not/writable")
    result = subprocess.run(
        [str(PYTHON), str(SCRIPT), "local", "--duration", "20", "--out", str(output)],
        capture_output=True,
        text=True,
        timeout=70,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_stop_and_blind_time_are_distinct_with_independent_truth(completed):
    collector = completed / "collector"
    result = json.loads((collector / "collection.json").read_text())
    measured = json.loads((collector / "oee.json").read_text())["measured"]
    assert result["samples_written"] > 100
    assert result["gaps"]
    assert measured["stopped_s"] > 1
    assert measured["unknown_s"] > 2
    assert measured["blind_windows_total"] >= 1
    events = [
        json.loads(line)
        for line in (completed / "simulator/simulator-events.jsonl").read_text().splitlines()
    ]
    cut = next(e for e in events if e["message"] == "relay_cut")
    restored = next(
        e for e in events if e["message"] == "relay_open" and stamp(e["ts"]) > stamp(cut["ts"])
    )
    ticks = [
        e
        for e in events
        if e["message"] == "tick" and stamp(cut["ts"]) <= stamp(e["ts"]) < stamp(restored["ts"])
    ]
    assert all(e["state"] == 2 for e in ticks)
    assert ticks[-1]["total_count"] > ticks[0]["total_count"]
    with (collector / "samples.csv").open() as stream:
        states = [r for r in csv.DictReader(stream) if r["tag"] == "0"]
    assert any(float(r["value"]) == 0 for r in states)
    assert any(stamp(r["ts"]) > stamp(restored["ts"]) and float(r["value"]) == 2 for r in states)
    timeline = json.loads((collector / "timeline.json").read_text())
    assert timeline["monitor_events_imported"] == 0
    assert any("First observation after blind interval" in e["message"] for e in timeline["events"])
    assert {e["source"] for e in timeline["events"]} == {
        "collector_observation",
        "fixture_truth",
        "relay_control",
    }


def report_args(completed, monitor):
    import argparse

    return argparse.Namespace(
        collector=completed / "collector",
        simulator_events=None,
        monitor_events=monitor,
        clocks_synchronized=False,
    )


def monitor_csv(tmp_path, completed, **overrides):
    run = json.loads((completed / "collector/run.json").read_text())
    entry = {
        "ts": run["start"],
        "run_id": run["run_id"],
        "host": run["host"],
        "port": run["port"],
        "message": "<script>alert('untrusted')</script>",
    }
    entry.update(overrides)
    path = tmp_path / "monitor.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(entry))
        writer.writeheader()
        writer.writerow(entry)
    return path


def test_monitor_import_keeps_provenance_clock_status_and_escapes_html(completed, tmp_path):
    path = monitor_csv(tmp_path, completed)
    joint.report(report_args(completed, path))
    collector = completed / "collector"
    timeline = json.loads((collector / "timeline.json").read_text())
    assert timeline["monitor_events_imported"] == 1
    assert timeline["clocks_confirmed_by_operator"] is False
    assert any(e["source"] == "monitor_import_unverified" for e in timeline["events"])
    document = (collector / "joint-report.html").read_text()
    assert "<script>" not in document
    assert "&lt;script&gt;" in document


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"run_id": "another-run"}, "must match"),
        ({"host": "192.0.2.9"}, "must match"),
        ({"port": 9999}, "must match"),
        ({"ts": "2026-11-13T12:00:00"}, "UTC offset"),
    ],
)
def test_unrelated_or_ambiguous_monitor_events_are_rejected(completed, tmp_path, overrides, reason):
    path = monitor_csv(tmp_path, completed, **overrides)
    with pytest.raises(ValueError, match=reason):
        joint.report(report_args(completed, path))


def test_invalid_empty_monitor_schema_is_rejected(completed, tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("wrong,headers\n")
    with pytest.raises(ValueError, match="headers"):
        joint.report(report_args(completed, path))


def test_relay_rejects_network_writes_and_cleans_up_backend(tmp_path):
    output = tmp_path / "simulator"
    process = subprocess.Popen(
        [str(PYTHON), str(SCRIPT), "simulator", "--port", "0", "--out", str(output)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if (output / "ready.json").exists():
                break
            assert process.poll() is None
            time.sleep(0.1)
        ready = json.loads((output / "ready.json").read_text())
        # FC06 attempts to alter run state through the public interface.
        with socket.create_connection(("127.0.0.1", ready["port"]), timeout=3) as client:
            client.sendall(struct.pack(">HHHBBHH", 1, 0, 6, 1, 6, 0, 0))
            response = bytearray()
            while len(response) < 9:
                response.extend(client.recv(9 - len(response)))
            assert response[-2:] == bytes([0x86, 1])
            # Valid read proves the state remained RUNNING.
            client.sendall(struct.pack(">HHHBBHH", 2, 0, 6, 1, 3, 0, 1))
            response = bytearray()
            while len(response) < 11:
                response.extend(client.recv(11 - len(response)))
            assert response[-2:] == bytes([0, 2])
    finally:
        process.terminate()
        process.wait(timeout=10)
    # Cancellation must close both the public relay and private child server.
    for port in [ready["port"], ready["private_backend_port"]]:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)


def test_existing_output_is_never_overwritten(tmp_path):
    (tmp_path / "keep.txt").write_text("existing evidence")
    with pytest.raises(ValueError, match="must be empty"):
        joint.fresh_output(tmp_path)
    assert (tmp_path / "keep.txt").read_text() == "existing evidence"


def test_fixture_file_cannot_impersonate_monitor_evidence(completed, tmp_path):
    run = json.loads((completed / "collector/run.json").read_text())
    path = tmp_path / "spoofed.jsonl"
    path.write_text(
        json.dumps(
            {
                "run_id": run["run_id"],
                "ts": run["start"],
                "source": "monitor_import_unverified",
                "message": "fake finding",
            }
        )
        + "\n"
    )
    args = report_args(completed, None)
    args.simulator_events = path
    with pytest.raises(ValueError, match="impersonate"):
        joint.report(args)
