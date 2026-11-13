"""Independent Tahu encoding → real MQTT broker → released iaiops tap.

This tests decoder interoperability, not a complete Tahu EoN state machine/TCK.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import mqtt_tap_session
from iaiops.core.runtime.session_factory import OTNoReadingError


def eventually(read, expected=None, error=None):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            result = read()
            if error is None and result[0] == expected:
                return result
        except OTNoReadingError as exc:
            if error and error in str(exc):
                return str(exc)
        time.sleep(0.03)
    raise AssertionError(f"observation did not reach expected value/error: {expected}, {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tahu-core", required=True, type=Path)
    parser.add_argument("--port", type=int, default=18883)
    args = parser.parse_args()
    env = dict(
        os.environ,
        PYTHONPATH=str(args.tahu_core.resolve()),
        PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="python",
    )
    fixture = json.loads(
        subprocess.check_output(
            [sys.executable, str(Path(__file__).with_name("encode_fixture.py"))],
            env=env,
        )
    )
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect("127.0.0.1", args.port)
    client.loop_start()
    target = TargetConfig(
        name="tahu-interop",
        protocol="mqtt",
        host="127.0.0.1",
        port=args.port,
        topic="spBv1.0/iaiops-community/#",
        stale_after_s=3.0,
        timeout_s=3.0,
    )
    results = []
    prefix = "spBv1.0/iaiops-community"
    power = "iaiops-community/node:Power"
    energy = "iaiops-community/node:Energy"

    def publish(kind, key):
        client.publish(
            f"{prefix}/{kind}/node", base64.b64decode(fixture[key]), qos=1
        ).wait_for_publish(timeout=3)

    try:
        with mqtt_tap_session(target) as reader:
            tap = reader.iaiops_uns_tap
            time.sleep(0.2)
            publish("NBIRTH", "birth")
            value, timestamp = eventually(lambda: tap.read(power), 42.0)
            results.append("Tahu NBIRTH named metric")
            assert (
                int(datetime.fromisoformat(timestamp).timestamp() * 1000) == fixture["timestamp_ms"]
            )
            results.append("epoch-millisecond source timestamp")
            publish("NDATA", "data")
            eventually(lambda: tap.read(power), 43.0)
            results.append("alias-only NDATA")
            publish("NDEATH", "death")
            eventually(lambda: tap.read(power), error="DEAD")
            results.append("NDEATH refuses cached value")
            publish("NBIRTH", "rebirth")
            eventually(lambda: tap.read(energy), 44.0)
            eventually(lambda: tap.read(power), error="Nothing has been published")
            results.append("NBIRTH replaces alias and removes old metric")
            time.sleep(3.2)
            eventually(lambda: tap.read(energy), error="stale_after_s")
            results.append("silence refuses stale value")
    finally:
        client.disconnect()
        client.loop_stop()
    print(
        json.dumps(
            {
                "status": "PASS",
                "checks": results,
                "tahu_commit": "5736e404889d4b95910613040a99ba79589ffb13",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
