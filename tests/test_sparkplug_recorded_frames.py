"""Replay a Sparkplug B stream recorded from a real broker through the tap.

Every other Sparkplug test here builds its payloads from protobuf inside the
test, which means they are shaped the way our decoder expects. That is exactly
how a green suite once missed that a spec-correct node names its metrics ONCE,
in NBIRTH, and sends aliases alone ever after: the tap kept serving the BIRTH
value and a counter sitting at 200 read as 0 and looked fresh.

These bytes were recorded by ``tests/data/sparkplug/capture.py`` as a real
mosquitto broker delivered them — including an NDEATH the broker published as
the node's Last Will after the node was ``kill -9``ed. The node is ours, written
from the spec; it is not a vendor device (see ``manifest.json``).

Expected values below are decoded INDEPENDENTLY of ``ops`` (straight from the
protobuf, alias looked up by number), so a decoder bug cannot make the test
agree with itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("google.protobuf")

from iaiops.connectors.sparkplug import sparkplug_b_pb2 as pb  # noqa: E402
from iaiops.connectors.sparkplug.tap import REF_SEP, UnsTap  # noqa: E402
from iaiops.core.runtime.session_factory import OTNoReadingError  # noqa: E402

pytestmark = pytest.mark.unit

DATA = Path(__file__).parent / "data" / "sparkplug"
MANIFEST = json.loads((DATA / "manifest.json").read_text())
NODE = "Plant1/Line2"
ALIAS = MANIFEST["aliases"]  # {"Running": 11, "PartCount": 12, "Temp": 13}


def _ref(metric: str) -> str:
    return f"{NODE}{REF_SEP}{metric}"


@dataclass
class _Target:
    name: str = "uns-recorded"
    protocol: str = "mqtt"
    stale_after_s: float = 30.0
    topic: str = "spBv1.0/#"
    timeout_s: float = 5.0
    tags: tuple = field(default_factory=tuple)


def _frames() -> list[tuple[dict, bytes]]:
    return [(f, (DATA / "frames" / f["file"]).read_bytes()) for f in MANIFEST["frames"]]


def _payload(raw: bytes):
    p = pb.Payload()
    p.ParseFromString(raw)
    return p


def _by_alias(raw: bytes, metric: str):
    """The value of ``metric`` in an NDATA frame, found by alias number alone."""
    for m in _payload(raw).metrics:
        if m.HasField("alias") and m.alias == ALIAS[metric]:
            if m.datatype == pb.Boolean:
                return m.boolean_value, m.timestamp
            if m.datatype in (pb.Int64, pb.UInt64):
                return m.long_value, m.timestamp
            return m.double_value, m.timestamp
    raise AssertionError(f"{metric} missing from frame")


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


class TestTheCorpusIsWhatItClaims:
    """If the corpus drifted, every test below could pass for the wrong reason."""

    def test_bytes_are_unchanged_since_recording(self):
        for meta, raw in _frames():
            assert hashlib.sha256(raw).hexdigest() == meta["sha256"], meta["file"]

    def test_stream_is_birth_then_data_then_a_broker_published_death(self):
        kinds = [m["topic"].split("/")[2] for m in MANIFEST["frames"]]
        assert kinds[0] == "NBIRTH" and kinds[-1] == "NDEATH"
        assert set(kinds[1:-1]) == {"NDATA"} and len(kinds) == 122

    def test_the_death_came_from_keepalive_expiry_not_a_closed_socket(self):
        """The node was frozen, not killed: its socket stayed open, so the broker
        could only declare it dead once keepalive expired (1.5x, per MQTT). That
        is a pulled cable, and it means a subscriber gets NO death signal for
        several seconds — the window `stale_after_s` exists to cover."""
        gap = MANIFEST["ndeath_after_last_ndata_s"]
        assert gap >= MANIFEST["keepalive_s"], gap

    def test_no_data_frame_carries_a_metric_name(self):
        """The property the whole file exists for. A corpus re-recorded by a
        node that sends names would silently turn every test here hollow."""
        entries = [
            m for meta, raw in _frames() if "NDATA" in meta["file"] for m in _payload(raw).metrics
        ]
        assert len(entries) == 360
        assert not any(m.name for m in entries)
        assert all(m.HasField("alias") for m in entries)


class TestReplayThroughTheTap:
    def _tap(self, **kw) -> UnsTap:
        return UnsTap(client=object(), target=_Target(**kw))

    def test_every_update_is_read_not_the_birth_value(self):
        """After each alias-only NDATA the tap returns THAT frame's values."""
        tap = self._tap()
        frames = _frames()
        tap.on_message(frames[0][0]["topic"], frames[0][1])
        for meta, raw in frames[1:-1]:
            tap.on_message(meta["topic"], raw)
            for metric in ALIAS:
                want, ts = _by_alias(raw, metric)
                got, got_ts = tap.read(_ref(metric))
                assert got == pytest.approx(want), (meta["file"], metric)
                assert got_ts == _iso(ts), "the node's timestamp, not arrival time"

    def test_the_final_counter_is_the_last_published_one(self):
        tap = self._tap()
        for meta, raw in _frames()[:-1]:
            tap.on_message(meta["topic"], raw)
        assert tap.read(_ref("PartCount"))[0] == 310
        assert tap.read(_ref("Running"))[0] is True

    def test_the_stopped_window_reads_as_stopped_and_the_counter_holds(self):
        first, last = MANIFEST["stopped_frames"]
        tap = self._tap()
        held = set()
        for n, (meta, raw) in enumerate(_frames()[:-1]):
            tap.on_message(meta["topic"], raw)
            if first <= n <= last:
                assert tap.read(_ref("Running"))[0] is False
                held.add(tap.read(_ref("PartCount"))[0])
        assert len(held) == 1

    def test_joining_mid_stream_names_nothing(self):
        """Without the BIRTH an alias cannot be named, so there is no reading —
        rather than a guess at which metric alias 12 might be."""
        tap = self._tap()
        for meta, raw in _frames()[1:-1]:
            tap.on_message(meta["topic"], raw)
        for metric in ALIAS:
            # "0 other point(s)": nothing was cached under an alias number
            # either — a bare alias is not a name, and serving it as one would
            # outlive the next BIRTH that reassigns it.
            with pytest.raises(
                OTNoReadingError, match=r"Nothing has been published.*\(0 other point"
            ):
                tap.read(_ref(metric))

    def test_the_broker_published_death_ends_every_reading(self):
        tap = self._tap()
        for meta, raw in _frames():
            tap.on_message(meta["topic"], raw)
        for metric in ALIAS:
            with pytest.raises(OTNoReadingError, match="DEAD"):
                tap.read(_ref(metric))
