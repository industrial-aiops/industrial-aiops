"""End-to-end live-broker test for the UNS live bridge (opt-in, real paho I/O).

Unlike ``test_uns_live.py`` (which injects messages through the callback), this
publishes real messages to a real broker and captures them through the FULL paho
loop — the only way to prove the live path actually works against paho 2.x.

It is SKIPPED unless a broker is reachable on ``IAIOPS_TEST_MQTT_HOST``:``_PORT``
(default 127.0.0.1:1883), so the normal quality gate never depends on a broker.
Stand one up cheaply to run it::

    docker run -d --rm -p 1883:1883 eclipse-mosquitto
    pytest -m integration tests/test_uns_live_integration.py

待核实: validated locally against eclipse-mosquitto; not exercised in CI (no
broker), and not validated against a production EoN-node / Sparkplug host.
"""

from __future__ import annotations

import os
import socket
import time

import pytest

from iaiops.connectors.sparkplug import live
from iaiops.core.runtime.config import TargetConfig

_HOST = os.environ.get("IAIOPS_TEST_MQTT_HOST", "127.0.0.1")
_PORT = int(os.environ.get("IAIOPS_TEST_MQTT_PORT", "1883"))


def _broker_reachable() -> bool:
    try:
        with socket.create_connection((_HOST, _PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _broker_reachable(),
        reason=f"no MQTT broker at {_HOST}:{_PORT} (start eclipse-mosquitto to run)",
    ),
]


def _pb():
    from iaiops.connectors.sparkplug import sparkplug_b_pb2

    return sparkplug_b_pb2


def _nbirth() -> bytes:
    pb = _pb()
    p = pb.Payload()
    p.timestamp = 1000
    p.seq = 0
    m = p.metrics.add()
    m.name = "Temperature"
    m.alias = 1
    m.datatype = 10  # Double
    m.double_value = 21.5
    return p.SerializeToString()


def _publish(target: TargetConfig, items: list[tuple[str, bytes]]) -> None:
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(target.host, target.port or 1883)
    client.loop_start()
    try:
        for topic, payload in items:
            client.publish(topic, payload=payload, qos=1, retain=True).wait_for_publish(5)
    finally:
        client.loop_stop()
        client.disconnect()


def test_live_audit_and_schema_against_real_broker() -> None:
    target = TargetConfig(name="uns-it", protocol="mqtt", host=_HOST, port=_PORT)
    _publish(target, [
        ("spBv1.0/PlantIT/NBIRTH/Edge1", _nbirth()),
        ("Enterprise/Site/Line1/temperature", b"21.5"),
    ])
    time.sleep(0.3)  # let the retained messages settle

    audit = live.uns_live_audit(target, topic="#", duration_s=3, max_msgs=50)
    assert audit["capture"]["observed_messages"] >= 2

    schema = live.sparkplug_live_schema(target, topic="spBv1.0/#", duration_s=3, max_msgs=50)
    assert schema["birth_count"] >= 1
    assert schema["schema"]["PlantIT/Edge1"] == {"Temperature": "Double"}
