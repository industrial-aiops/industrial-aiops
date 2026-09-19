"""Record a Sparkplug B stream as a real broker delivers it, for replay tests.

Two roles in one file:

* ``node`` — a minimal edge node written from the Sparkplug B 3.0 spec, not from
  our decoder: it names its metrics ONCE in NBIRTH and sends aliases alone in
  every NDATA, and it registers its NDEATH as the MQTT Last Will.
* the default role — subscribes to ``spBv1.0/#`` on a broker, starts the node as
  a subprocess, records every payload exactly as the broker delivered it, then
  ``kill -9``s the node so the NDEATH in the corpus is one the BROKER published,
  not one we wrote to disk ourselves.

Why this exists: every payload in ``test_uns_tap.py`` is built by the test from
protobuf, i.e. shaped the way the decoder expects. That is how a green suite once
missed that a real node sends names only in the BIRTH. Recorded bytes are not
shaped by anything we believe.

Provenance, stated plainly: the broker is a real third-party mosquitto; the node
is ours. So this is a real wire and a real broker — NOT a vendor device.

Run (writes ``frames/`` and ``manifest.json`` next to this file):

    docker run -d --rm --name iaiops-mosq -p 127.0.0.1:21883:1883 \\
        eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
    .venv/bin/python tests/data/sparkplug/capture.py --port 21883
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROUP, NODE = "Plant1", "Line2"
PREFIX = f"spBv1.0/{GROUP}"
NDATA_COUNT = 120
PERIOD_S = 1.0
#: Frames in which the line is stopped: Running=False and the counter holds.
STOPPED = range(61, 71)
#: Alias per data metric. Names travel only in NBIRTH.
ALIASES = {"Running": 11, "PartCount": 12, "Temp": 13}
BDSEQ = 0
#: The node's MQTT keepalive. A frozen node is declared dead by the broker only
#: after 1.5x this, which is the gap a field cable-pull produces.
KEEPALIVE_S = 5


def _pb():
    from iaiops.connectors.sparkplug import sparkplug_b_pb2 as pb

    return pb


def _values(i: int) -> dict:
    """Deterministic line state for frame ``i`` (0 = the BIRTH)."""
    produced = sum(1 for k in range(1, i + 1) if k not in STOPPED)
    return {
        "Running": i not in STOPPED,
        "PartCount": 200 + produced,
        "Temp": round(40.0 + 0.05 * i, 2),
    }


def _add(payload, *, name=None, alias=None, dtype, value, ts):
    pb = _pb()
    m = payload.metrics.add()
    if name is not None:
        m.name = name
    if alias is not None:
        m.alias = alias
    m.timestamp = ts
    m.datatype = dtype
    if dtype == pb.Boolean:
        m.boolean_value = bool(value)
    elif dtype in (pb.Int64, pb.UInt64):
        m.long_value = int(value)
    else:
        m.double_value = float(value)


def _data_metrics(payload, i: int, ts: int, *, with_names: bool) -> None:
    pb = _pb()
    v = _values(i)
    types = {"Running": pb.Boolean, "PartCount": pb.Int64, "Temp": pb.Double}
    for key, alias in ALIASES.items():
        _add(
            payload,
            name=key if with_names else None,
            alias=alias,
            dtype=types[key],
            value=v[key],
            ts=ts,
        )


def _now_ms() -> int:
    return int(time.time() * 1000)


def run_node(host: str, port: int) -> None:
    """The edge node. Publishes until killed; never disconnects cleanly."""
    import paho.mqtt.client as mqtt

    pb = _pb()
    death = pb.Payload()
    death.timestamp = _now_ms()
    _add(death, name="bdSeq", dtype=pb.UInt64, value=BDSEQ, ts=death.timestamp)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="iaiops-capture-node")
    client.will_set(f"{PREFIX}/NDEATH/{NODE}", death.SerializeToString(), qos=1, retain=False)
    client.connect(host, port, keepalive=KEEPALIVE_S)
    client.loop_start()
    time.sleep(0.5)

    birth = pb.Payload()
    birth.timestamp = _now_ms()
    birth.seq = 0
    _add(birth, name="bdSeq", dtype=pb.UInt64, value=BDSEQ, ts=birth.timestamp)
    _add(birth, name="Node Control/Rebirth", dtype=pb.Boolean, value=False, ts=birth.timestamp)
    _data_metrics(birth, 0, birth.timestamp, with_names=True)
    client.publish(f"{PREFIX}/NBIRTH/{NODE}", birth.SerializeToString(), qos=0).wait_for_publish()

    for i in range(1, NDATA_COUNT + 1):
        time.sleep(PERIOD_S)
        data = pb.Payload()
        data.timestamp = _now_ms()
        data.seq = i % 256
        _data_metrics(data, i, data.timestamp, with_names=False)
        client.publish(f"{PREFIX}/NDATA/{NODE}", data.SerializeToString(), qos=0).wait_for_publish()
    print("NODE-DONE", flush=True)
    while True:  # wait to be killed: a clean DISCONNECT would suppress the Will
        time.sleep(1)


def capture(host: str, port: int, broker: str, node_cmd: str, death_cmd: str, death: str) -> None:
    import paho.mqtt.client as mqtt

    got: list[dict] = []
    died = threading.Event()
    t0 = time.monotonic()

    def on_message(_c, _u, msg):
        kind = msg.topic.split("/")[2]
        got.append(
            {
                "topic": msg.topic,
                "qos": msg.qos,
                "retain": bool(msg.retain),
                "payload": bytes(msg.payload),
                "kind": kind,
                "arrived_s": round(time.monotonic() - t0, 3),
            }
        )
        if kind == "NDEATH":
            died.set()

    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="iaiops-capture-recorder")
    sub.on_message = on_message
    sub.connect(host, port, keepalive=30)
    sub.subscribe("spBv1.0/#", qos=1)
    sub.loop_start()
    time.sleep(0.5)

    cmd = (
        shlex.split(node_cmd)
        if node_cmd
        else [sys.executable, __file__, "--role", "node", "--host", host, "--port", str(port)]
    )
    node = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        for line in node.stdout:
            if line.startswith("NODE-DONE"):
                break
        time.sleep(0.5)
        # Never a clean DISCONNECT: that would suppress the Will. Either kill the
        # process (the socket closes, the broker notices at once) or freeze it
        # (the socket stays up, the broker notices only when keepalive expires).
        if death_cmd:
            subprocess.run(shlex.split(death_cmd), check=True)
        else:
            os.kill(node.pid, signal.SIGKILL)
        if not died.wait(30):
            raise SystemExit("broker never published the NDEATH Last Will")
        time.sleep(0.3)
    finally:
        if node.poll() is None:
            node.kill()
        sub.loop_stop()
        sub.disconnect()

    kinds = [g["kind"] for g in got]
    want = ["NBIRTH"] + ["NDATA"] * NDATA_COUNT + ["NDEATH"]
    if kinds != want:
        raise SystemExit(f"unexpected stream shape: {kinds[:3]}… ({len(kinds)} messages)")

    last_data = got[-2]["arrived_s"]
    death_gap = round(got[-1]["arrived_s"] - last_data, 3)

    frames = HERE / "frames"
    frames.mkdir(exist_ok=True)
    for old in frames.glob("*.bin"):
        old.unlink()
    manifest = []
    for n, g in enumerate(got):
        name = f"{n:03d}-{g['kind']}.bin"
        (frames / name).write_bytes(g["payload"])
        manifest.append(
            {
                "file": name,
                "topic": g["topic"],
                "qos": g["qos"],
                "retain": g["retain"],
                "bytes": len(g["payload"]),
                "sha256": hashlib.sha256(g["payload"]).hexdigest(),
                "arrived_s": g["arrived_s"],
            }
        )
    (HERE / "manifest.json").write_text(
        json.dumps(
            {
                "broker": broker,
                "node": "capture.py (ours, written from the Sparkplug B 3.0 spec)",
                "not": "a vendor device",
                "death": death,
                "keepalive_s": KEEPALIVE_S,
                "ndeath_after_last_ndata_s": death_gap,
                "stopped_frames": [STOPPED.start, STOPPED.stop - 1],
                "aliases": ALIASES,
                "frames": manifest,
            },
            indent=1,
        )
        + "\n"
    )
    print(f"recorded {len(manifest)} frames -> {frames}; NDEATH {death_gap}s after last NDATA")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["capture", "node"], default="capture")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=21883)
    ap.add_argument("--broker", default="eclipse-mosquitto:2 (docker)")
    ap.add_argument("--node-cmd", default="", help="start the node elsewhere (e.g. over ssh)")
    ap.add_argument("--death-cmd", default="", help="end the node elsewhere; default kill -9")
    ap.add_argument("--death", default="kill -9 (socket closed; broker notices at once)")
    a = ap.parse_args()
    if a.role == "node":
        run_node(a.host, a.port)
    else:
        capture(a.host, a.port, a.broker, a.node_cmd, a.death_cmd, a.death)


if __name__ == "__main__":
    main()
