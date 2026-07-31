"""A RETAINED mqtt_publish is reversible, and the undo descriptor must say so.

``mqtt_publish`` was the one high-risk write exempted from the undo requirement,
on the grounds that a published message cannot be unsent. That is true of a
TRANSIENT publish and false of a retained one: ``retain=True`` REPLACES the
broker's retained message on that topic — durable state every later subscriber
receives — and the payload it replaced is readable beforehand and restorable after.

So the tool now captures the BEFORE state (as the protocol write tools do) and
records an inverse, while still returning None for the cases genuinely without one.
Those None cases are the interesting half of this file: an undo descriptor that
over-promises is worse than none at all, because an operator would replay it onto a
live broker.

The live half (``test_*_live``) runs the real round-trip against a real broker
through the full paho loop; it skips when no broker is reachable and runs in CI,
where the gate job stands up mosquitto.
"""

from __future__ import annotations

import os
import socket
import time
import uuid

import pytest

from iaiops.connectors.sparkplug import ops
from iaiops.core.runtime.config import TargetConfig
from mcp_server.tools.sparkplug_tools import _mqtt_undo

_HOST = os.environ.get("IAIOPS_TEST_MQTT_HOST", "127.0.0.1")
_PORT = int(os.environ.get("IAIOPS_TEST_MQTT_PORT", "1883"))


def _broker_reachable() -> bool:
    try:
        with socket.create_connection((_HOST, _PORT), timeout=1.0):
            return True
    except OSError:
        return False


# ── the inverse must not over-promise ────────────────────────────────────────

_APPLIED_RETAINED = {
    "applied": True,
    "retain": True,
    "before": {"found": True, "payload": "21.5", "binary": False},
}
_PARAMS = {"endpoint": "uns", "topic": "factory/line1/setpoint", "qos": 1}


@pytest.mark.unit
def test_retained_publish_records_the_prior_payload() -> None:
    undo = _mqtt_undo(_PARAMS, _APPLIED_RETAINED)
    assert undo is not None
    assert undo["tool"] == "mqtt_publish"
    assert undo["params"]["payload"] == "21.5"
    assert undo["params"]["topic"] == "factory/line1/setpoint"
    assert undo["params"]["retain"] is True
    assert undo["params"]["dry_run"] is False, "an inverse that previews restores nothing"


@pytest.mark.unit
def test_undo_of_a_first_retained_publish_clears_the_retained_message() -> None:
    """Nothing was retained before, so the inverse is a zero-byte retained publish —
    how MQTT deletes a retained message. Restoring 'nothing' as an empty payload is
    the only faithful inverse; leaving the new value in place would not be one."""
    undo = _mqtt_undo(
        _PARAMS,
        {"applied": True, "retain": True, "before": {"found": False, "payload": None}},
    )
    assert undo is not None
    assert undo["params"]["payload"] == ""
    assert "Clear" in undo["note"]


@pytest.mark.unit
def test_transient_publish_has_no_inverse() -> None:
    """Delivered is delivered — this is the case the blanket exemption was right about."""
    assert _mqtt_undo(_PARAMS, {"applied": True, "retain": False}) is None


@pytest.mark.unit
def test_dry_run_records_no_inverse() -> None:
    """A preview changed nothing; there is nothing to reverse."""
    assert _mqtt_undo(_PARAMS, {"dry_run": True, "retain": True}) is None


@pytest.mark.unit
def test_failed_capture_records_no_inverse() -> None:
    """A capture error must NOT be read as 'nothing was retained' — that would make
    the inverse clear a retained message the operator never set."""
    assert (
        _mqtt_undo(
            _PARAMS,
            {"applied": True, "retain": True, "before": {"found": False, "error": "timeout"}},
        )
        is None
    )


@pytest.mark.unit
def test_binary_prior_payload_records_no_inverse() -> None:
    """A Sparkplug protobuf cannot round-trip through a ``str`` payload parameter.
    No inverse beats a lossy one that would corrupt the topic on replay."""
    assert (
        _mqtt_undo(
            _PARAMS,
            {"applied": True, "retain": True, "before": {"found": True, "binary": True}},
        )
        is None
    )


@pytest.mark.unit
def test_non_dict_result_is_tolerated() -> None:
    assert _mqtt_undo(_PARAMS, None) is None
    assert _mqtt_undo(_PARAMS, "error string") is None


# ── real broker ──────────────────────────────────────────────────────────────

pytestmark_live = pytest.mark.skipif(
    not _broker_reachable(),
    reason=f"no MQTT broker at {_HOST}:{_PORT} (start eclipse-mosquitto to run)",
)


def _target() -> TargetConfig:
    return TargetConfig(name="retained-it", protocol="mqtt", host=_HOST, port=_PORT)


@pytest.mark.integration
@pytestmark_live
def test_capture_retained_reads_what_the_broker_holds_live() -> None:
    """The BEFORE capture against a real broker: a retained message must be seen,
    and a topic with nothing retained must report found=False rather than hang."""
    target = _target()
    topic = f"iaiops-test/{uuid.uuid4().hex}/setpoint"

    empty = ops.capture_retained(target, topic)
    assert empty["found"] is False and "error" not in empty

    ops.mqtt_publish(target, topic, "21.5", qos=1, retain=True, dry_run=False)
    time.sleep(0.3)

    captured = ops.capture_retained(target, topic)
    assert captured["found"] is True
    assert captured["payload"] == "21.5"
    assert captured["binary"] is False


@pytest.mark.integration
@pytestmark_live
def test_retained_publish_captures_before_and_the_inverse_restores_it_live() -> None:
    """Full round-trip on a real broker: seed → overwrite → apply the recorded
    inverse → the broker holds the original again. This is the claim the undo
    descriptor makes; here it is executed rather than asserted."""
    target = _target()
    topic = f"iaiops-test/{uuid.uuid4().hex}/setpoint"

    ops.mqtt_publish(target, topic, "21.5", qos=1, retain=True, dry_run=False)
    time.sleep(0.3)

    result = ops.mqtt_publish(target, topic, "80.0", qos=1, retain=True, dry_run=False)
    assert result["before"] == {"found": True, "payload": "21.5", "binary": False}
    time.sleep(0.3)
    assert ops.capture_retained(target, topic)["payload"] == "80.0"

    undo = _mqtt_undo({"endpoint": target.name, "topic": topic, "qos": 1}, result)
    assert undo is not None
    ops.mqtt_publish(
        target,
        undo["params"]["topic"],
        undo["params"]["payload"],
        qos=undo["params"]["qos"],
        retain=True,
        dry_run=False,
    )
    time.sleep(0.3)

    assert ops.capture_retained(target, topic)["payload"] == "21.5", (
        "the recorded inverse did not restore the prior retained payload"
    )

    # Leave the broker as we found it — a retained message outlives the test run.
    ops.mqtt_publish(target, topic, "", qos=1, retain=True, dry_run=False)


@pytest.mark.integration
@pytestmark_live
def test_transient_publish_does_not_touch_retained_state_live() -> None:
    """retain=False must neither capture nor overwrite: the topic's retained
    message is whatever it already was, and the result carries no ``before``."""
    target = _target()
    topic = f"iaiops-test/{uuid.uuid4().hex}/cmd"

    ops.mqtt_publish(target, topic, "21.5", qos=1, retain=True, dry_run=False)
    time.sleep(0.3)

    result = ops.mqtt_publish(target, topic, "80.0", qos=1, retain=False, dry_run=False)
    assert "before" not in result
    time.sleep(0.3)
    assert ops.capture_retained(target, topic)["payload"] == "21.5"

    ops.mqtt_publish(target, topic, "", qos=1, retain=True, dry_run=False)
