"""MTConnect ops tests against static XML fixtures (no live agent).

The module-level ``_http_get`` is monkeypatched to return realistic MTConnect
Probe / Current / Sample / Assets documents, so the XML parsing, observation
extraction, and OEE snapshot logic are exercised for real.
"""

from __future__ import annotations

import re

import pytest

from iaiops.connectors.mtconnect import ops
from iaiops.core.runtime.config import TargetConfig

_NS_DEV = "urn:mtconnect.org:MTConnectDevices:1.7"
_NS_STREAMS = "urn:mtconnect.org:MTConnectStreams:1.7"
_NS_ASSETS = "urn:mtconnect.org:MTConnectAssets:1.7"

PROBE_XML = f"""<?xml version="1.0"?>
<MTConnectDevices xmlns="{_NS_DEV}">
  <Header creationTime="2026-06-28T10:00:00Z" instanceId="1" sender="agent"/>
  <Devices>
    <Device id="d1" name="VMC1" uuid="VMC1-001">
      <Components>
        <Axes id="ax" name="Axes">
          <Components>
            <Linear id="x" name="X">
              <DataItems>
                <DataItem id="xpos" type="POSITION" category="SAMPLE" name="Xact"
                          units="MILLIMETER"/>
              </DataItems>
            </Linear>
          </Components>
        </Axes>
        <Controller id="ctrl" name="Controller">
          <DataItems>
            <DataItem id="avail" type="AVAILABILITY" category="EVENT"/>
            <DataItem id="exec" type="EXECUTION" category="EVENT"/>
            <DataItem id="mode" type="CONTROLLER_MODE" category="EVENT"/>
            <DataItem id="prog" type="PROGRAM" category="EVENT"/>
          </DataItems>
        </Controller>
      </Components>
    </Device>
  </Devices>
</MTConnectDevices>"""

CURRENT_XML = f"""<?xml version="1.0"?>
<MTConnectStreams xmlns="{_NS_STREAMS}">
  <Header creationTime="2026-06-28T10:00:01Z" instanceId="1" sender="agent"/>
  <Streams>
    <DeviceStream name="VMC1" uuid="VMC1-001">
      <ComponentStream component="Controller" name="Controller" componentId="ctrl">
        <Events>
          <Availability dataItemId="avail" timestamp="2026-06-28T10:00:00Z"
                        sequence="1">AVAILABLE</Availability>
          <Execution dataItemId="exec" timestamp="2026-06-28T10:00:00Z"
                     sequence="2">ACTIVE</Execution>
          <ControllerMode dataItemId="mode" timestamp="2026-06-28T10:00:00Z"
                          sequence="3">AUTOMATIC</ControllerMode>
          <Program dataItemId="prog" timestamp="2026-06-28T10:00:00Z"
                   sequence="4">O1234</Program>
        </Events>
      </ComponentStream>
      <ComponentStream component="Linear" name="X" componentId="x">
        <Samples>
          <Position dataItemId="xpos" timestamp="2026-06-28T10:00:00Z"
                    sequence="5">12.5</Position>
        </Samples>
      </ComponentStream>
    </DeviceStream>
  </Streams>
</MTConnectStreams>"""

ASSETS_XML = f"""<?xml version="1.0"?>
<MTConnectAssets xmlns="{_NS_ASSETS}">
  <Header creationTime="2026-06-28T10:00:02Z" instanceId="1" sender="agent"/>
  <Assets>
    <CuttingTool assetId="T1" timestamp="2026-06-28T09:00:00Z"/>
    <CuttingTool assetId="T2" timestamp="2026-06-28T09:30:00Z"/>
  </Assets>
</MTConnectAssets>"""


@pytest.fixture
def cnc_target(monkeypatch):
    def _fake_get(url, timeout=10):
        if url.endswith("/probe"):
            return PROBE_XML
        if "/sample" in url:
            return CURRENT_XML  # same stream shape suffices for the test
        if url.endswith("/current"):
            return CURRENT_XML
        if url.endswith("/assets"):
            return ASSETS_XML
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(ops, "_http_get", _fake_get)
    return TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")


@pytest.mark.unit
def test_probe_models_device(cnc_target):
    out = ops.mtconnect_probe(cnc_target)
    assert out["device_count"] == 1
    dev = out["devices"][0]
    assert dev["name"] == "VMC1" and dev["uuid"] == "VMC1-001"
    ids = {di["id"] for comp in dev["components"] for di in comp["data_items"]}
    assert {"xpos", "avail", "exec", "prog"} <= ids


@pytest.mark.unit
def test_current_observations(cnc_target):
    out = ops.mtconnect_current(cnc_target)
    by_id = {o["data_item_id"]: o for o in out["observations"]}
    assert by_id["avail"]["value"] == "AVAILABLE"
    assert by_id["xpos"]["value"] == "12.5"
    assert by_id["exec"]["timestamp"].startswith("2026-06-28")


@pytest.mark.unit
def test_sample_is_bounded(cnc_target):
    out = ops.mtconnect_sample(cnc_target, count=10000)
    assert out["requested_count"] <= ops.MAX_SAMPLE_COUNT


@pytest.mark.unit
def test_assets(cnc_target):
    out = ops.mtconnect_assets(cnc_target)
    assert out["asset_count"] == 2
    assert {a["asset_id"] for a in out["assets"]} == {"T1", "T2"}


@pytest.mark.unit
def test_xml_with_dtd_is_rejected(monkeypatch):
    evil = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]>'
        "<MTConnectStreams><Streams/></MTConnectStreams>"
    )
    monkeypatch.setattr(ops, "_http_get", lambda url, timeout=10: evil)
    target = TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")
    with pytest.raises(ValueError, match="DTD/entity"):
        ops.mtconnect_current(target)


# ── response size cap (streamed fetch; memory-DoS defense) ────────────────────


class _FakeStreamResponse:
    """Stands in for requests' streamed Response: chunked body, no network."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.chunks_served = 0

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for chunk in self._chunks:
            self.chunks_served += 1
            yield chunk

    def close(self):
        pass


def _patch_requests_get(monkeypatch, response):
    import requests

    def _fake_get(url, timeout=10, stream=False):
        assert stream is True  # the fetch must stream, not buffer via resp.text
        return response

    monkeypatch.setattr(requests, "get", _fake_get)


@pytest.mark.unit
def test_http_get_refuses_oversized_response(monkeypatch):
    """A body over the 4 MiB cap is refused mid-stream, not read into memory."""
    chunks = [b"x" * 1_048_576] * 8  # 8 MiB total, 1 MiB chunks
    resp = _FakeStreamResponse(chunks)
    _patch_requests_get(monkeypatch, resp)
    with pytest.raises(ValueError, match="response size cap"):
        ops._http_get("http://h:5000/current")
    assert resp.chunks_served < len(chunks)  # aborted before draining the body


@pytest.mark.unit
def test_http_get_normal_response_streams_through(monkeypatch):
    body = CURRENT_XML.encode()
    chunks = [body[i : i + 1000] for i in range(0, len(body), 1000)]
    _patch_requests_get(monkeypatch, _FakeStreamResponse(chunks))
    target = TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")
    out = ops.mtconnect_current(target)  # full real path through the capped fetch
    assert out["observation_count"] > 0


@pytest.mark.unit
def test_http_get_rejects_doctype_on_first_chunk(monkeypatch):
    """The DTD/entity guard runs on the FIRST chunk, before the rest downloads."""
    evil_head = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]>'
    resp = _FakeStreamResponse([evil_head, b"<x>" + b"y" * 4096 + b"</x>"])
    _patch_requests_get(monkeypatch, resp)
    with pytest.raises(ValueError, match="DTD/entity"):
        ops._http_get("http://h:5000/current")
    assert resp.chunks_served == 1  # refused without consuming the remainder


@pytest.mark.unit
def test_oee_snapshot_running(cnc_target):
    out = ops.mtconnect_oee_snapshot(cnc_target)
    assert out["availability"] == "AVAILABLE"
    assert out["execution"] == "ACTIVE"
    assert out["controller_mode"] == "AUTOMATIC"
    assert out["program"] == "O1234"
    assert out["available"] is True and out["running"] is True
    assert out["verdict"] == "running"


# ── incremental long-poll streaming (mtconnect_stream + sequence-aware sample) ──


def _streams_doc(
    observations: list[tuple[str, int, str]],
    next_sequence: int,
    instance_id: str = "1",
) -> str:
    """Build a MTConnectStreams document with a sequence-bearing <Header>.

    ``observations`` is a list of ``(dataItemId, sequence, value)`` Position samples;
    the header advertises ``nextSequence`` (the cursor a client passes as ``from=``).
    """
    samples = "".join(
        f'<Position dataItemId="{did}" timestamp="2026-06-28T10:00:00Z" '
        f'sequence="{seq}">{val}</Position>'
        for did, seq, val in observations
    )
    return (
        '<?xml version="1.0"?>'
        f'<MTConnectStreams xmlns="{_NS_STREAMS}">'
        f'<Header creationTime="2026-06-28T10:00:00Z" instanceId="{instance_id}" '
        f'sender="agent" nextSequence="{next_sequence}" firstSequence="1" '
        f'lastSequence="{max(next_sequence - 1, 1)}"/>'
        '<Streams><DeviceStream name="VMC1" uuid="VMC1-001">'
        '<ComponentStream component="Linear" name="X" componentId="x">'
        f"<Samples>{samples}</Samples>"
        "</ComponentStream></DeviceStream></Streams>"
        "</MTConnectStreams>"
    )


def _from_arg(url: str) -> int | None:
    m = re.search(r"[?&]from=(\d+)", url)
    return int(m.group(1)) if m else None


def _stream_target(monkeypatch, fake_get) -> TargetConfig:
    monkeypatch.setattr(ops, "_http_get", fake_get)
    monkeypatch.setattr(ops, "_sleep", lambda _s: None)  # no real waits in tests
    return TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")


@pytest.mark.unit
def test_stream_advances_by_sequence_then_stops_caught_up(monkeypatch):
    """Two incremental pages advance the cursor; an empty page ends the stream."""

    def _fake_get(url, timeout=10):
        frm = _from_arg(url)
        if frm is None:
            return _streams_doc([("xpos", 1, "1.0"), ("xpos", 2, "2.0")], next_sequence=3)
        if frm == 3:
            return _streams_doc([("xpos", 3, "3.0"), ("xpos", 4, "4.0")], next_sequence=5)
        if frm == 5:
            return _streams_doc([], next_sequence=5)  # caught up
        raise AssertionError(f"unexpected from={frm}")

    target = _stream_target(monkeypatch, _fake_get)
    out = ops.mtconnect_stream(
        target, from_sequence=None, interval_ms=0, count=10, max_samples=100, duration_s=60
    )
    assert out["mode"] == "stream"
    assert [o["sequence"] for o in out["observations"]] == ["1", "2", "3", "4"]
    assert out["observation_count"] == 4
    assert out["next_sequence"] == 5
    assert out["stopped_reason"] == "caught_up"
    assert out["poll_count"] == 3


@pytest.mark.unit
def test_stream_stops_at_max_samples(monkeypatch):
    """A perpetually-advancing agent is bounded by the max_samples budget."""

    def _fake_get(url, timeout=10):
        frm = _from_arg(url) or 1
        return _streams_doc([("xpos", frm, "a"), ("xpos", frm + 1, "b")], next_sequence=frm + 2)

    target = _stream_target(monkeypatch, _fake_get)
    out = ops.mtconnect_stream(
        target, from_sequence=1, interval_ms=0, count=10, max_samples=5, duration_s=60
    )
    assert out["observation_count"] == 5  # never exceeds the budget
    assert out["stopped_reason"] == "max_samples"


@pytest.mark.unit
def test_stream_stops_at_max_polls_and_spaces_by_interval(monkeypatch):
    """The iteration cap bounds an endless agent; interval spacing is applied."""
    sleeps: list[float] = []

    def _fake_get(url, timeout=10):
        frm = _from_arg(url) or 1
        return _streams_doc([("xpos", frm, "a")], next_sequence=frm + 1)

    monkeypatch.setattr(ops, "_http_get", _fake_get)
    monkeypatch.setattr(ops, "_sleep", lambda s: sleeps.append(s))
    target = TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")

    out = ops.mtconnect_stream(
        target, from_sequence=1, interval_ms=250, count=10, max_samples=100_000, duration_s=120
    )
    assert out["poll_count"] == ops.MAX_STREAM_POLLS
    assert out["stopped_reason"] == "max_polls"
    assert sleeps and all(s == 0.25 for s in sleeps)  # interval_ms honored


@pytest.mark.unit
def test_stream_stops_when_agent_instance_resets(monkeypatch):
    """A changed instanceId (agent restart) invalidates the cursor → stop."""

    def _fake_get(url, timeout=10):
        frm = _from_arg(url) or 1
        if frm == 1:
            return _streams_doc([("xpos", 1, "a")], next_sequence=2, instance_id="1")
        return _streams_doc([("xpos", 2, "b")], next_sequence=3, instance_id="2")

    target = _stream_target(monkeypatch, _fake_get)
    out = ops.mtconnect_stream(
        target, from_sequence=1, interval_ms=0, count=10, max_samples=100, duration_s=60
    )
    assert out["stopped_reason"] == "instance_changed"
    assert out["observation_count"] == 1  # data from the reset buffer is discarded


@pytest.mark.unit
def test_sample_incremental_page_sends_from_and_returns_next_sequence(monkeypatch):
    """A from_sequence snapshot page sends from=/count= and surfaces next_sequence."""
    captured: dict[str, str] = {}

    def _fake_get(url, timeout=10):
        captured["url"] = url
        return _streams_doc([("xpos", 7, "9.9")], next_sequence=8)

    monkeypatch.setattr(ops, "_http_get", _fake_get)
    target = TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")

    out = ops.mtconnect_sample(target, count=50, from_sequence=7)
    assert "from=7" in captured["url"] and "count=50" in captured["url"]
    assert out["mode"] == "snapshot"
    assert out["from_sequence"] == 7
    assert out["next_sequence"] == 8
    assert out["observation_count"] == 1


@pytest.mark.unit
def test_current_exposes_next_sequence(monkeypatch):
    """/current surfaces next_sequence so a caller can start a stream at 'now'."""
    monkeypatch.setattr(
        ops, "_http_get", lambda url, timeout=10: _streams_doc([("xpos", 5, "1.0")], 6)
    )
    target = TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")
    out = ops.mtconnect_current(target)
    assert out["next_sequence"] == 6
    assert out["observation_count"] == 1
