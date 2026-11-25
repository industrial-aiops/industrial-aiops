"""A tap session cannot advertise readiness before broker subscription acceptance."""

import threading
from types import SimpleNamespace

import pytest

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import _subscribe_tap
from iaiops.core.runtime.session_factory import OTConnectionError


class Client:
    on_subscribe = None

    def __init__(self, *, codes=(0,), ack=True, rc=0, mid=17):
        self.codes, self.ack, self.rc, self.mid = codes, ack, rc, mid
        self.ready = threading.Event()
        self.timer = None

    def is_connected(self):
        return True

    def subscribe(self, topic):
        def accept():
            self.ready.set()
            if self.on_subscribe:
                self.on_subscribe(self, None, self.mid, self.codes, None)

        if self.ack:
            self.timer = threading.Timer(0.03, accept)
            self.timer.start()
        return self.rc, 17


def target():
    return TargetConfig(
        name="test",
        protocol="mqtt",
        host="localhost",
        topic="line/#",
        stale_after_s=3,
        timeout_s=0.1,
    )


def test_waits_for_subscription_before_one_shot_publish():
    client = Client()
    try:
        _subscribe_tap(client, target())
        assert client.ready.is_set(), "one-shot publish would be lost before subscription exists"
        client.on_message(None, None, SimpleNamespace(topic="line/run", payload=b"42"))
        assert client.iaiops_uns_tap.read("line/run")[0] == 42
    finally:
        client.timer.join()


@pytest.mark.parametrize(
    "options",
    [
        {"codes": (128,)},
        {"codes": ()},
        {"ack": False},
        {"rc": 4, "ack": False},
        {"mid": 18},
    ],
)
def test_refuses_denied_missing_failed_or_wrong_ack(options):
    client = Client(**options)
    try:
        with pytest.raises(OTConnectionError):
            _subscribe_tap(client, target())
    finally:
        if client.timer:
            client.timer.join()


def test_connack_timeout_never_sends_subscribe():
    client = Client()
    client.is_connected = lambda: False
    with pytest.raises(OTConnectionError, match="connection.*acknowledged"):
        _subscribe_tap(client, target())
    assert client.timer is None


def test_ack_arriving_before_subscribe_returns_is_not_lost():
    client = Client()

    def subscribe(topic):
        client.on_subscribe(client, None, 17, (0,), None)
        return 0, 17

    client.subscribe = subscribe
    _subscribe_tap(client, target())
    assert client.on_subscribe is None
