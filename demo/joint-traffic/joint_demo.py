"""Software-only traffic/production exercise; no monitor integration is assumed."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import html
import ipaddress
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def phase(elapsed: float, duration: int) -> tuple[int, bool]:
    """Fixture semantics: run=2, stop=0; the outage never stops production."""
    return (
        0 if 0.2 * duration <= elapsed < 0.35 * duration else 2,
        0.55 * duration <= elapsed < 0.75 * duration,
    )


def fresh_output(path: Path) -> Path:
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(path.iterdir()):
        raise ValueError(f"Output directory must be empty: {path}")
    return path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def event(path: Path, run_id: str, kind: str, message: str, **extra: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"ts": utc(), "run_id": run_id, "source": kind, "message": message, **extra})
            + "\n"
        )


async def simulator(args: argparse.Namespace) -> None:
    """Loopback pymodbus server + local fixture driver + read-only TCP relay."""
    from pymodbus.client import ModbusTcpClient

    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, task.cancel)
    address = ipaddress.ip_address(args.bind)
    if not address.is_loopback and not args.lab_network:
        raise ValueError("Non-loopback bind requires --lab-network on an isolated lab segment")
    out = fresh_output(args.out)
    backend_port = free_port()
    log = (out / "backend.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "demo/oee-line/simulate_line.py"),
            "serve",
            "--port",
            str(backend_port),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    started: float | None = None
    active: set[asyncio.StreamWriter] = set()
    events = out / "simulator-events.jsonl"
    writer_client = ModbusTcpClient("127.0.0.1", port=backend_port, timeout=1)

    async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal started
        active.add(writer)
        upstream = None
        try:
            while True:
                header = await reader.readexactly(7)
                _, protocol, length, _ = struct.unpack(">HHHB", header)
                if protocol != 0 or not 2 <= length <= 254:
                    return
                body = await reader.readexactly(length - 1)
                # Only known holding-register reads reach the synthetic backend.
                if (
                    len(body) != 5
                    or body[0] != 3
                    or struct.unpack(">HH", body[1:]) not in {(0, 1), (10, 1), (11, 1)}
                ):
                    writer.write(
                        header[:4] + struct.pack(">HB", 3, header[6]) + bytes([body[0] | 0x80, 1])
                    )
                    await writer.drain()
                    continue
                if started is None:
                    started = time.monotonic()
                    event(events, args.run_id, "fixture_truth", "scenario_started")
                _, blocked = phase(time.monotonic() - started, args.duration)
                if blocked:
                    return
                upstream_reader, upstream = await asyncio.open_connection("127.0.0.1", backend_port)
                upstream.write(header + body)
                await upstream.drain()
                response_header = await asyncio.wait_for(upstream_reader.readexactly(7), 2)
                response_length = struct.unpack(">H", response_header[4:6])[0]
                response = await asyncio.wait_for(
                    upstream_reader.readexactly(response_length - 1), 2
                )
                writer.write(response_header + response)
                await writer.drain()
                upstream.close()
                await upstream.wait_closed()
                upstream = None
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, OSError):
            pass  # A deliberate relay cut disconnects the collection session.
        finally:
            active.discard(writer)
            writer.close()
            if upstream:
                upstream.close()

    async def drive() -> None:
        counter = good = 0
        previous = None
        waiting_since = time.monotonic()
        while started is None or time.monotonic() - started < args.duration + 5:
            if started is None and time.monotonic() - waiting_since > args.wait_timeout:
                raise TimeoutError("No valid collection read before --wait-timeout")
            elapsed = 0 if started is None else time.monotonic() - started
            state, blocked = phase(elapsed, args.duration)
            if state == 2:
                counter += 1
                good += int(counter % 25 != 0)
            # Only this fixture driver writes, only to its private loopback simulator.
            for ref, value in [(0, state), (10, counter), (11, good)]:
                response = await asyncio.to_thread(
                    writer_client.write_register, ref, value % 65535, device_id=1
                )
                if response.isError():
                    raise RuntimeError("Synthetic backend rejected fixture update")
            if started is not None and (state, blocked) != previous:
                event(
                    events,
                    args.run_id,
                    "fixture_truth",
                    "production_state",
                    state=state,
                    total_count=counter,
                    good_count=good,
                )
                if previous is None or previous[1] != blocked:
                    event(
                        events,
                        args.run_id,
                        "relay_control",
                        "relay_cut" if blocked else "relay_open",
                        detail="Application TCP relay control; not packet capture or firewall loss",
                    )
                if blocked:
                    for connection in list(active):
                        connection.close()
                previous = (state, blocked)
            if started is not None:
                event(
                    events,
                    args.run_id,
                    "fixture_truth",
                    "tick",
                    state=state,
                    total_count=counter,
                    good_count=good,
                )
            await asyncio.sleep(0.1)
        event(events, args.run_id, "fixture_truth", "scenario_finished")

    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Synthetic server exited; inspect backend.log")
            if await asyncio.to_thread(writer_client.connect):
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Synthetic server did not become ready")
        initial = await asyncio.to_thread(writer_client.write_register, 0, 2, device_id=1)
        if initial.isError():
            raise RuntimeError("Could not initialize synthetic running state")
        server = await asyncio.start_server(relay, args.bind, args.port)
        port = server.sockets[0].getsockname()[1]
        write_json(
            out / "ready.json",
            {
                "run_id": args.run_id,
                "host": args.bind,
                "port": port,
                "private_backend_port": backend_port,
                "duration_s": args.duration,
                "ready_at": utc(),
            },
        )
        print(f"Ready on {args.bind}:{port}; waiting for first valid read", flush=True)
        async with server:
            await asyncio.wait_for(drive(), timeout=args.duration + args.wait_timeout + 10)
    finally:
        for connection in list(active):
            connection.close()
        writer_client.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


def collect(args: argparse.Namespace) -> None:
    if not ipaddress.ip_address(args.host).is_loopback and not args.lab_network:
        raise ValueError("Non-loopback collector requires --lab-network for this test fixture")
    out = fresh_output(args.out)
    home = out / "home"
    home.mkdir(mode=0o700)
    config_dir = home / ".iaiops"
    config_dir.mkdir(mode=0o700)
    # Roles below are authored fixture definitions, never inferred device semantics.
    config = {
        "endpoints": [
            {
                "name": "demo-line",
                "protocol": "modbus",
                "host": args.host,
                "port": args.port,
                "unit_id": 1,
                "ideal_cycle_time_s": 0.1,
                "stale_after_s": 1.5,
                "tags": [
                    {
                        "ref": "0",
                        "label": "Synthetic run state",
                        "role": "run_state",
                        "running_when": [2],
                    },
                    {"ref": "10", "label": "Synthetic count", "role": "total_count"},
                    {"ref": "11", "label": "Synthetic good count", "role": "good_count"},
                ],
            }
        ]
    }
    # JSON is valid YAML, avoiding an extra authoring dependency here.
    write_json(config_dir / "config.yaml", config)
    (config_dir / "config.yaml").chmod(0o600)
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("IAIOPS_", "OT_AIOPS_", "PYTHON"))
    }
    env.update(HOME=str(home), IAIOPS_NO_EGRESS="1", NO_COLOR="1", TERM="dumb")
    executable = Path(sys.executable).parent / "iaiops"

    def cli(arguments: list[str], filename: str) -> str:
        result = subprocess.run(
            [str(executable), *arguments],
            env=env,
            cwd=out,
            capture_output=True,
            text=True,
            timeout=args.duration + 45,
        )
        (out / filename).write_text(result.stdout, encoding="utf-8")
        (out / (filename + ".stderr")).write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"iaiops failed; inspect {out / filename} and .stderr")
        return result.stdout

    start = utc()
    result = json.loads(
        cli(
            [
                "collect",
                "run",
                "demo-line",
                "--duration",
                f"{args.duration}s",
                "--interval-ms",
                "200",
                "--json",
            ],
            "collection.json",
        )
    )
    end = utc()
    write_json(
        out / "run.json",
        {
            "run_id": args.run_id,
            "host": args.host,
            "port": args.port,
            "start": start,
            "end": end,
            "evidence": "software fixture; not physical PLC evidence",
        },
    )
    cli(
        ["export", "csv", "--out", str(out / "samples.csv"), "--endpoint", "demo-line"],
        "export.json",
    )
    oee_args = [
        "oee",
        "measure",
        "demo-line",
        "--since",
        start,
        "--until",
        end,
        "--minor-stop-s",
        "1",
        "--note",
        "Synthetic lab fixture. Gaps are unobserved time, not proven downtime.",
    ]
    cli([*oee_args, "--json"], "oee.json")
    cli([*oee_args, "--report", str(out / "oee.html")], "oee-report.log")
    print(f"Collected {result['samples_written']} samples; output: {out}", flush=True)
    report(
        argparse.Namespace(
            collector=out, simulator_events=None, monitor_events=None, clocks_synchronized=False
        )
    )


def report(args: argparse.Namespace) -> None:
    out = args.collector.resolve()
    run = json.loads((out / "run.json").read_text())
    result = json.loads((out / "collection.json").read_text())
    measured = json.loads((out / "oee.json").read_text())["measured"]
    rows = []
    for gap in result["gaps"]:
        rows.append(
            {
                "ts": gap["from_ts"],
                "source": "collector_observation",
                "message": f"Collection blind until {gap['to_ts']}; not proven downtime",
            }
        )
    with (out / "samples.csv").open(newline="", encoding="utf-8") as stream:
        states = [r for r in csv.DictReader(stream) if r["tag"] == "0"]
    previous = None
    previous_ts = None
    for sample in states:
        state = str(sample["value"])
        timestamp = datetime.fromisoformat(sample["ts"])
        recovered = (
            previous_ts is not None
            and (timestamp - previous_ts).total_seconds() > measured["blind_gap_limit_s"]
        )
        if state != previous or recovered:
            prefix = "First observation after blind interval: " if recovered else ""
            rows.append(
                {
                    "ts": sample["ts"],
                    "source": "collector_observation",
                    "message": prefix
                    + f"Observed synthetic run-state {state} (2=running, 0=stopped)",
                }
            )
            previous = state
        previous_ts = timestamp
    if args.simulator_events:
        for line in args.simulator_events.read_text().splitlines():
            entry = json.loads(line)
            if entry["run_id"] != run["run_id"]:
                raise ValueError("Simulator event run_id mismatch")
            if entry["source"] not in {"fixture_truth", "relay_control"}:
                raise ValueError("Simulator events cannot impersonate other evidence sources")
            if entry["message"] != "tick":
                message = {
                    "scenario_started": "Scenario started on the first valid read",
                    "scenario_finished": "Scenario completed",
                    "relay_cut": "Lab relay cut; synthetic production continues",
                    "relay_open": "Lab relay accepts collection connections",
                }.get(entry["message"], entry["message"])
                if entry["message"] == "production_state":
                    label = "running" if entry["state"] == 2 else "stopped"
                    message = (
                        f"Synthetic production {label}; total {entry['total_count']}, "
                        f"good {entry['good_count']}"
                    )
                rows.append({**entry, "message": message})
    monitor_count = 0
    if args.monitor_events:
        with args.monitor_events.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if not {"ts", "run_id", "host", "port", "message"} <= set(reader.fieldnames or []):
                raise ValueError("Monitor CSV requires ts,run_id,host,port,message headers")
            for entry in reader:
                if (
                    entry["run_id"] != run["run_id"]
                    or entry["host"] != run["host"]
                    or int(entry["port"]) != run["port"]
                ):
                    raise ValueError("Monitor event must match run_id and simulator host/port")
                timestamp = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
                if timestamp.utcoffset() is None:
                    raise ValueError("Monitor timestamps need an explicit UTC offset")
                rows.append(
                    {
                        "ts": timestamp.astimezone(UTC).isoformat(),
                        "source": "monitor_import_unverified",
                        "message": entry["message"],
                    }
                )
                monitor_count += 1
    rows.sort(key=lambda row: datetime.fromisoformat(row["ts"].replace("Z", "+00:00")))
    payload = {
        "run": run,
        "monitor_events_imported": monitor_count,
        "clocks_confirmed_by_operator": args.clocks_synchronized,
        "events": rows,
    }
    write_json(out / "timeline.json", payload)
    with (out / "timeline.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["ts", "source", "message"], extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    source_labels = {
        "collector_observation": "Collector observation",
        "fixture_truth": "Simulator ground truth",
        "relay_control": "Relay control (lab injection)",
        "monitor_import_unverified": "Monitor import (unverified)",
    }
    table_rows = []
    for row in rows:
        timestamp = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        display = [
            timestamp.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            source_labels[row["source"]],
            row["message"],
        ]
        table_rows.append(
            "<tr>" + "".join(f"<td>{html.escape(text)}</td>" for text in display) + "</tr>"
        )
    table = "".join(table_rows)
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Production state and communication evidence</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:40px auto;padding:16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:8px;
text-align:left;overflow-wrap:anywhere}}
td:first-child{{white-space:nowrap;font-size:13px;font-variant-numeric:tabular-nums}}
td:nth-child(2){{min-width:150px}}.note{{background:#fff3cd;padding:16px}}</style>
<h1>Production stop or collection blind spot?</h1>
<p>Run: {html.escape(run["run_id"])} | Software-only synthetic Modbus line.</p>
<p>Collected {result["samples_written"]} samples;
successful attempted reads {result["coverage_pct"]}%.
Observed-time coverage {measured["coverage_pct"]}%; observed stopped time
{measured["stopped_s"]}s; unobserved time {measured["unknown_s"]}s.
These coverage measures have different denominators.
Imported monitor events: {monitor_count}.</p>
<p class="note">Collector observations, fixture ground truth and relay-control events
are separate evidence sources. Imported monitor events are supplied by the operator;
identity and content have not been independently verified. A relay cut is an application-level
connection cutoff, not a measured switch failure or packet-loss test.
Clock synchronization confirmed by operator: {args.clocks_synchronized}.
Cross-host timing requires synchronized clocks; this table makes no automatic root-cause claim.
Unobserved time is not observed production downtime.</p>
<p><a href="oee.html">OEE detail</a> · <a href="samples.csv">Samples</a> ·
<a href="timeline.csv">Timeline CSV</a></p>
<table><thead><tr><th>Timestamp</th><th>Evidence source</th><th>Event</th></tr></thead>
<tbody>{table}</tbody></table></html>"""
    (out / "joint-report.html").write_text(document, encoding="utf-8")
    print(f"Report: {out / 'joint-report.html'}", flush=True)


def local(args: argparse.Namespace) -> None:
    out = fresh_output(args.out)
    with (out / "simulator.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                __file__,
                "simulator",
                "--port",
                "0",
                "--duration",
                str(args.duration),
                "--run-id",
                args.run_id,
                "--out",
                str(out / "simulator"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            ready_path = out / "simulator/ready.json"
            for _ in range(200):
                if ready_path.exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"Simulator exited; inspect {out / 'simulator.log'}")
                time.sleep(0.1)
            else:
                raise RuntimeError("Simulator readiness timeout")
            ready = json.loads(ready_path.read_text())
            collect(
                argparse.Namespace(
                    host="127.0.0.1",
                    port=ready["port"],
                    duration=args.duration + 3,
                    run_id=args.run_id,
                    out=out / "collector",
                    lab_network=False,
                )
            )
            process.wait(timeout=20)
            if process.returncode:
                raise RuntimeError("Simulator failed")
            report(
                argparse.Namespace(
                    collector=out / "collector",
                    simulator_events=out / "simulator/simulator-events.jsonl",
                    monitor_events=None,
                    clocks_synchronized=False,
                )
            )
        finally:
            if process.poll() is None:
                process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)
                if process.poll() is None:
                    process.kill()
                    process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["local", "simulator", "collect"]:
        cmd = commands.add_parser(name)
        cmd.add_argument("--out", type=Path, required=True, help="New or empty output directory")
        cmd.add_argument("--duration", type=int, default=90)
        cmd.add_argument("--run-id", default="joint-demo-1")
        if name in {"simulator", "collect"}:
            cmd.add_argument("--port", type=int, default=15020)
            cmd.add_argument("--lab-network", action="store_true")
        if name == "simulator":
            cmd.add_argument("--bind", default="127.0.0.1")
            cmd.add_argument("--wait-timeout", type=int, default=300)
        if name == "collect":
            cmd.add_argument("--host", required=True)
    cmd = commands.add_parser("report")
    cmd.add_argument("--collector", type=Path, required=True)
    cmd.add_argument("--simulator-events", type=Path)
    cmd.add_argument("--monitor-events", type=Path)
    cmd.add_argument("--clocks-synchronized", action="store_true")
    args = parser.parse_args()
    if hasattr(args, "duration") and not 20 <= args.duration <= 3600:
        parser.error("--duration must be between 20 and 3600 seconds")
    if hasattr(args, "wait_timeout") and not 1 <= args.wait_timeout <= 3600:
        parser.error("--wait-timeout must be between 1 and 3600 seconds")
    if args.command == "simulator":
        try:
            asyncio.run(simulator(args))
        except asyncio.CancelledError:
            pass  # SIGINT/SIGTERM cleanup has completed inside simulator().
    else:
        {"local": local, "collect": collect, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
