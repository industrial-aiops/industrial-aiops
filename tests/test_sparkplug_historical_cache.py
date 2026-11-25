"""Synthetic protobuf replay of live-cache semantics; no broker or gateway."""

from types import SimpleNamespace

import pytest

from iaiops.connectors.sparkplug import sparkplug_b_pb2 as pb
from iaiops.connectors.sparkplug.tap import UnsTap
from iaiops.core.runtime.session_factory import OTNoReadingError


def payload(*values, birth=False, alias=False):
    p = pb.Payload()
    for value, historical in values:
        m = p.metrics.add()
        if birth or not alias:
            m.name = "Temperature"
        m.alias = 1
        m.datatype = 9
        m.float_value = value
        m.timestamp = 1_700_000_000_000 if historical else 1_800_000_000_000
        m.is_historical = historical
    return p.SerializeToString()


@pytest.mark.parametrize("device", [False, True], ids=["node", "device"])
@pytest.mark.parametrize("alias", [False, True], ids=["named", "alias"])
def test_historical_replay_preserves_live_value_and_original_expiry(monkeypatch, device, alias):
    clock = [100.0]
    monkeypatch.setattr("iaiops.connectors.sparkplug.tap.time.monotonic", lambda: clock[0])
    tap = UnsTap(object(), SimpleNamespace(name="fixture", stale_after_s=10))
    kind, suffix = ("D", "/device") if device else ("N", "")
    topic = f"spBv1.0/lab/{kind}DATA/node{suffix}"
    ref = f"lab/node{suffix}:Temperature"
    tap.on_message(f"spBv1.0/lab/{kind}BIRTH/node{suffix}", payload((22, False), birth=True))
    before = tap.read(ref)
    clock[0] = 109.0
    tap.on_message(topic, payload((5, True), alias=alias))
    assert tap.read(ref) == before
    clock[0] = 111.0
    with pytest.raises(OTNoReadingError, match="[Ss][Tt][Aa][Ll][Ee]"):
        tap.read(ref)
    # Even continuous backlog after expiry must not revive the live reading.
    tap.on_message(topic, payload((6, True), alias=alias))
    with pytest.raises(OTNoReadingError):
        tap.read(ref)
    tap.on_message(topic, payload((24, False), alias=alias))
    assert tap.read(ref)[0] == 24


@pytest.mark.parametrize(
    "values", [((5, True),), ((24, False), (5, True)), ((5, True), (24, False))]
)
def test_history_only_is_not_live_and_mixed_payload_keeps_current_metric(values):
    tap = UnsTap(object(), SimpleNamespace(name="fixture", stale_after_s=10))
    tap.on_message("spBv1.0/lab/NDATA/node", payload(*values))
    if len(values) == 1:
        with pytest.raises(OTNoReadingError):
            tap.read("lab/node:Temperature")
    else:
        assert tap.read("lab/node:Temperature")[0] == 24
