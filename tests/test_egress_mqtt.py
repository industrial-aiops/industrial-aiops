"""MQTT/UNS stream egress — topic shaping + JSON payload (delivery mocked, no broker)."""

import pytest

from iaiops.core.egress import EgressError, get_publisher
from iaiops.core.egress.base import points_to_mqtt_messages
from iaiops.core.egress.mqtt import MQTTPublisher
from iaiops.core.sink.base import normalize_points


@pytest.mark.unit
def test_topic_is_slash_separated_not_dotted():
    """MQTT hierarchies use '/', unlike the NATS subject tree's '.'.

    A dotted metric must become one topic *level* under the prefix, not a dotted
    leaf: a UNS subscriber filters on levels, so 'plant/line1/temp' is browsable
    where 'plant/line1.temp' is an opaque leaf.
    """
    pts = normalize_points([{"ref": "line1.temp", "value": 21.5}])
    msgs = points_to_mqtt_messages(pts, "plant")
    assert len(msgs) == 1
    topic, payload = msgs[0]
    assert topic == "plant/line1/temp"
    assert payload["value"] == 21.5


@pytest.mark.unit
def test_non_numeric_points_are_skipped():
    """Same rule as the NATS path: a bus carries live values; text/state goes to a sink."""
    pts = normalize_points(
        [
            {"ref": "a", "value": 1.0},
            {"ref": "b", "value": "OPEN"},
        ]
    )
    assert len(points_to_mqtt_messages(pts, "p")) == 1


@pytest.mark.unit
def test_wildcards_are_stripped_from_a_published_topic():
    """'+' and '#' are subscribe-side wildcards; publishing them is a protocol error.

    A tag name is operator-supplied and can contain anything, so the builder has to
    neutralise them rather than trust the caller.
    """
    pts = normalize_points([{"ref": "a+b#c", "value": 1.0}])
    topic, _ = points_to_mqtt_messages(pts, "p")[0]
    assert "+" not in topic
    assert "#" not in topic


@pytest.mark.unit
def test_prefix_wildcards_are_stripped_too():
    """The prefix is caller-supplied as well and gets the same treatment."""
    pts = normalize_points([{"ref": "a", "value": 1.0}])
    topic, _ = points_to_mqtt_messages(pts, "pl+nt/#")[0]
    assert "+" not in topic
    assert "#" not in topic


@pytest.mark.unit
def test_empty_levels_are_dropped():
    """'//' would publish to an empty level — legal in MQTT but meaningless in a UNS."""
    pts = normalize_points([{"ref": "line1..temp", "value": 1.0}])
    topic, _ = points_to_mqtt_messages(pts, "p/")[0]
    assert "//" not in topic
    assert not topic.endswith("/")


@pytest.mark.unit
def test_publish_points_uses_deliver(monkeypatch):
    pub = MQTTPublisher(topic_prefix="p")
    captured: list = []
    monkeypatch.setattr(pub, "_deliver", lambda msgs: captured.extend(msgs))
    assert pub.publish_points(normalize_points([{"ref": "a", "value": 1.0}])) == 1
    assert captured[0][0] == "p/a"


@pytest.mark.unit
def test_publish_event_topic(monkeypatch):
    pub = MQTTPublisher(topic_prefix="p")
    captured: list = []
    monkeypatch.setattr(pub, "_deliver", lambda msgs: captured.extend(msgs))
    assert pub.publish_event("rca/verdict", {"primary_cause": "seal"}) == 1
    assert captured[0][0] == "p/rca/verdict"


@pytest.mark.unit
def test_payload_is_json_bytes(monkeypatch):
    """The wire form is the shared ``encode()`` — deterministic, sorted-key JSON."""
    import json

    pub = MQTTPublisher(topic_prefix="p")
    captured: list = []
    monkeypatch.setattr(pub, "_deliver", lambda msgs: captured.extend(msgs))
    pub.publish_points(normalize_points([{"ref": "a", "value": 1.5}]))
    decoded = json.loads(captured[0][1].decode("utf-8"))
    assert decoded["metric"] == "a"
    assert decoded["value"] == 1.5


@pytest.mark.unit
def test_deliver_to_an_unreachable_broker_raises_teaching_error():
    """Bounded failure, aimed at a port nothing can listen on.

    Mirrors the NATS test's reasoning: paho's connect does not bound itself either,
    and this tool is reachable from an MCP client, so an unreachable broker must
    surface an error the caller can act on rather than hanging. The elapsed
    assertion is the regression guard — without our own watchdog this blocks far
    longer than the nominal timeout.
    """
    import time

    publisher = MQTTPublisher(host="127.0.0.1", port=1, timeout_s=1)
    started = time.monotonic()
    with pytest.raises(EgressError):
        publisher._deliver([("t", b"{}")])
    assert time.monotonic() - started < 15


@pytest.mark.unit
def test_get_publisher():
    assert isinstance(get_publisher("mqtt"), MQTTPublisher)
    with pytest.raises(EgressError):
        get_publisher("kafka")


@pytest.mark.unit
def test_mqtt_is_advertised_as_supported():
    from iaiops.core.egress.base import SUPPORTED_PUBLISHERS

    assert "mqtt" in SUPPORTED_PUBLISHERS


@pytest.mark.unit
def test_nats_shaping_is_untouched():
    """The NATS builder must keep its dotted form — the two share a payload, not a topic."""
    from iaiops.core.egress.base import points_to_messages

    pts = normalize_points([{"ref": "line1.temp", "value": 21.5}])
    subject, _ = points_to_messages(pts, "plant")[0]
    assert subject == "plant.tag.line1_temp"
