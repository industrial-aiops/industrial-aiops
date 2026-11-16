"""Replay external Tahu-generated payloads; no broker, device or TCK claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PIN = "c19db8c926dcc8c1f28ad604a13d73d95f281323"


def generate(core):
    # Run only in the subprocess: old generated protobuf must not share iaiops' pool.
    sys.path.insert(0, str(core.resolve()))
    import sparkplug_b as tahu

    node, device, death = (
        tahu.getNodeBirthPayload(),
        tahu.getDeviceBirthPayload(),
        tahu.getNodeDeathPayload(),
    )
    tahu.addMetric(
        device, "Run", 1, tahu.MetricDataType.Int32, 1, timestamp=int(time.time() * 1000)
    )
    defaults = tahu.getDeviceBirthPayload()
    tahu.addMetric(defaults, "First", 2, tahu.MetricDataType.Int32, 1)
    time.sleep(0.05)
    tahu.addMetric(defaults, "Second", 3, tahu.MetricDataType.Int32, 2)
    frames = [
        ("spBv1.0/lab/NBIRTH/node", node),
        ("spBv1.0/lab/DBIRTH/node/device", device),
        ("spBv1.0/lab/NDEATH/node", death),
    ]
    return {
        "frames": [
            {"topic": topic, "hex": payload.SerializeToString().hex()} for topic, payload in frames
        ],
        "default_metric_timestamps": [m.timestamp for m in defaults.metrics],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-core", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--generate", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    expected = {
        "sparkplug_b.py": "967ad3df3a0d050168cc2e68003f6d15e545973df1392b4fb00cdb55f5ebc112",
        "sparkplug_b_pb2.py": "8297b74e5499befc42469c21714a9bb61e05e75e042e43589f1e4514bb4f2e41",
        "array_packer.py": "230a20e1d57ddac37ae87446c140d32b6975a671745b64eef1a94871fef48738",
    }
    for name, digest in expected.items():
        if hashlib.sha256((args.upstream_core / name).read_bytes()).hexdigest() != digest:
            parser.error(f"Upstream source hash mismatch: {name}")
    if args.generate:
        print(json.dumps(generate(args.upstream_core)))
        return
    if args.out.exists():
        parser.error("Output must not already exist")
    env = dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="python")
    generated = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                __file__,
                "--upstream-core",
                str(args.upstream_core),
                "--out",
                str(args.out),
                "--generate",
            ],
            env=env,
            text=True,
            timeout=30,
        )
    )
    from iaiops.connectors.sparkplug.tap import REF_SEP, UnsTap
    from iaiops.core.runtime.session_factory import OTNoReadingError

    tap = UnsTap(client=object(), target=SimpleNamespace(name="fixture", stale_after_s=300))
    frames = generated["frames"]
    for frame in frames[:2]:
        tap.on_message(frame["topic"], bytes.fromhex(frame["hex"]))
    ref = f"lab/node/device{REF_SEP}Run"
    before = tap.read(ref)[0]
    tap.on_message(frames[2]["topic"], bytes.fromhex(frames[2]["hex"]))
    try:
        after, refused = tap.read(ref)[0], False
    except OTNoReadingError:
        after, refused = None, True
    args.out.mkdir(parents=True)
    manifest = []
    for i, frame in enumerate(frames):
        data = bytes.fromhex(frame["hex"])
        name = f"{i:02d}.bin"
        (args.out / name).write_bytes(data)
        manifest.append(
            {"topic": frame["topic"], "file": name, "sha256": hashlib.sha256(data).hexdigest()}
        )
    timestamps = generated["default_metric_timestamps"]
    result = {
        "upstream_commit": PIN,
        "source_sha256": {
            name: hashlib.sha256((args.upstream_core / name).read_bytes()).hexdigest()
            for name in ["sparkplug_b.py", "sparkplug_b_pb2.py", "array_packer.py"]
        },
        "transport": "offline Tahu payloads; no broker/device/TCK",
        "before_node_death": before,
        "after_node_death": after,
        "device_read_refused": refused,
        "default_metric_timestamps": timestamps,
        "defaults_are_equal": timestamps[0] == timestamps[1],
        "frames": manifest,
    }
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
