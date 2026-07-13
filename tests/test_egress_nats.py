"""NATS stream egress — point/event shaping + routing (delivery mocked, no broker)."""

import pytest

from iaiops.core.egress import EgressError, get_publisher, points_to_messages
from iaiops.core.egress.nats import NATSPublisher
from iaiops.core.sink.base import normalize_points


@pytest.mark.unit
def test_points_to_messages_shaping():
    pts = normalize_points(
        [
            {"ref": "line1.temp", "value": 21.5, "timestamp": "2026-07-11T00:00:00Z"},
            {"ref": "x", "value": "OPEN"},
        ]
    )
    msgs = points_to_messages(pts, "plant")
    assert len(msgs) == 1  # non-numeric skipped
    subject, payload = msgs[0]
    assert subject == "plant.tag.line1_temp"
    assert payload["value"] == 21.5


@pytest.mark.unit
def test_publish_points_uses_deliver(monkeypatch):
    pub = NATSPublisher(subject_prefix="p")
    captured: list = []
    monkeypatch.setattr(pub, "_deliver", lambda msgs: captured.extend(msgs))
    assert pub.publish_points(normalize_points([{"ref": "a", "value": 1.0}])) == 1
    assert captured[0][0] == "p.tag.a"


@pytest.mark.unit
def test_publish_event_subject(monkeypatch):
    pub = NATSPublisher(subject_prefix="p")
    captured: list = []
    monkeypatch.setattr(pub, "_deliver", lambda msgs: captured.extend(msgs))
    assert pub.publish_event("rca.verdict", {"primary_cause": "seal"}) == 1
    assert captured[0][0] == "p.rca.verdict"


@pytest.mark.unit
def test_deliver_without_nats_raises_teaching_error():
    with pytest.raises(EgressError):
        NATSPublisher()._deliver([("s", b"{}")])


@pytest.mark.unit
def test_get_publisher():
    assert isinstance(get_publisher("nats"), NATSPublisher)
    with pytest.raises(EgressError):
        get_publisher("kafka")
