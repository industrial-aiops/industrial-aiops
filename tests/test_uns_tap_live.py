"""The MQTT tap against a REAL broker, through the full paho loop.

``test_uns_tap.py`` drives the cache directly, which proves the refusal logic and
nothing about paho. This publishes to a real broker and reads back through the
same session the collector holds open — the only way to know the subscription,
the callback signature and the teardown actually work on paho 2.x.

SKIPPED unless a broker is reachable on ``IAIOPS_TEST_MQTT_HOST``:``_PORT``
(default 127.0.0.1:1883), so the normal gate never depends on one::

    docker run -d --rm -p 1883:1883 eclipse-mosquitto
    pytest -m integration tests/test_uns_tap_live.py

Validated 2026-09-12 against eclipse-mosquitto:2. 待核实: not validated against a
production Sparkplug EoN node or a commercial broker (HiveMQ / EMQX).
"""

from __future__ import annotations

import os
import pathlib
import socket
import time

import pytest

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTNoReadingError

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
        reason=f"no MQTT broker on {_HOST}:{_PORT} (set IAIOPS_TEST_MQTT_HOST/_PORT)",
    ),
]

_TOPIC = "iaiops-test/tap/value"


def _target(stale_after_s: float = 3.0) -> TargetConfig:
    return TargetConfig(
        name="tap-live",
        protocol="mqtt",
        host=_HOST,
        port=_PORT,
        topic="iaiops-test/#",
        stale_after_s=stale_after_s,
        timeout_s=5.0,
    )


def _publish(payload: str) -> None:
    import paho.mqtt.client as mqtt

    client = (
        mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if hasattr(mqtt, "CallbackAPIVersion")
        else mqtt.Client()
    )
    client.connect(_HOST, _PORT)
    client.loop_start()
    client.publish(_TOPIC, payload, qos=1)
    time.sleep(0.3)
    client.loop_stop()
    client.disconnect()


def _wait_for(tap, ref, timeout_s=5.0):
    """Publish-and-poll until the value lands.

    Re-publishing on every attempt is deliberate: with a short ``stale_after_s``
    a value can arrive AND go stale between two polls, and a version of this
    helper that only waited reported "never arrived" for a value it had already
    seen and correctly expired.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return tap.read(ref)
        except OTNoReadingError:
            time.sleep(0.1)
    raise AssertionError(f"{ref!r} never arrived through the real broker")


def test_a_published_value_is_readable_through_the_held_session():
    from iaiops.core.runtime.connection import mqtt_tap_session

    with mqtt_tap_session(_target()) as client:
        tap = client.iaiops_uns_tap
        _publish("42.5")
        value, _ = _wait_for(tap, _TOPIC)
        assert value == 42.5


def test_a_publisher_that_stops_becomes_a_refusal_not_a_repeated_value():
    """The whole point, proved on real wire: the broker stays connected and the
    subscription stays alive, and the tap still stops answering."""
    from iaiops.core.runtime.connection import mqtt_tap_session

    stale_after_s = 2.0
    with mqtt_tap_session(_target(stale_after_s=stale_after_s)) as client:
        tap = client.iaiops_uns_tap
        _publish("7")
        assert _wait_for(tap, _TOPIC)[0] == 7
        time.sleep(stale_after_s + 0.6)  # nothing more is published
        with pytest.raises(OTNoReadingError, match="stale_after_s"):
            tap.read(_TOPIC)


def test_collection_records_the_silence_as_a_gap_and_keeps_running():
    """Through `collect_run`, not through the tap: a stale point must reach the
    collector as a blind window, and the run must survive it — an early version
    tore the session down on every refusal, which would drop the subscription
    (and its cache) whenever one slow metric went quiet."""
    import threading

    from iaiops.core.collect.plan import CollectionPlan
    from iaiops.core.collect.reader import session_builder_for, session_read_for
    from iaiops.core.collect.runner import run_collection

    target = _target(stale_after_s=1.5)
    plan = CollectionPlan(endpoint=target.name, tags=(_TOPIC,), duration_s=6, interval_ms=500)
    # Publish for the first two seconds only, then go quiet — a publisher dying
    # mid-run, which is the case a cache would paper over.
    threading.Thread(target=_publish_for, args=(2.0,), daemon=True).start()
    out = run_collection(
        plan,
        target,
        reader=session_read_for("mqtt"),
        db_path=_tmp_db(),
        session_builder=session_builder_for("mqtt"),
    ).as_dict()
    assert out["samples_written"] >= 1, out
    assert out["gaps"], "the silence after the publisher stopped must be recorded"
    assert any("stale_after_s" in str(g.get("reason", "")) for g in out["gaps"]), out["gaps"]


def _publish_for(seconds: float) -> None:
    end = time.monotonic() + seconds
    n = 0
    while time.monotonic() < end:
        n += 1
        _publish(str(n))
        time.sleep(0.3)


def _tmp_db():
    import tempfile

    return pathlib.Path(tempfile.mkdtemp()) / "live.db"


def test_can_collect_is_true_now_and_the_registry_agrees():
    from iaiops.core.collect.reader import can_collect, collectable_protocols

    assert can_collect("mqtt")
    assert "mqtt" in collectable_protocols()
