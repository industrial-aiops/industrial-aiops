"""Egress sinks against REAL servers — the paths that ship plant data off-box.

`test_egress_nats.py` monkeypatches `_deliver`; `test_influxdb_sink.py` replaces
the whole `requests` module. So the two things that actually leave the building —
the NATS wire format and the InfluxDB line protocol — were only ever checked
against our own idea of them.

That is a strange gap for exactly these tools: they are what `IAIOPS_NO_EGRESS`
exists to withhold, and `historian_push` / `stream_publish` were the ones that
leaked a credential into the audit log a day earlier. A path that carries data out
of a plant deserves a real counterparty.

Here a real **NATS** server (rung 2a — its own broker parses our subjects and
payloads) and a real **HTTP** endpoint recording exactly what the InfluxDB sink
puts on the wire (rung 2b for the line protocol itself: the endpoint is ours, but
the protocol is a documented text format we can assert byte-for-byte).

NATS skips when no broker is reachable; start one with::

    docker run -d --rm -p 4222:4222 nats:alpine
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytestmark = [pytest.mark.integration]

_NATS_HOST = "127.0.0.1"
_NATS_PORT = 4222


def _nats_reachable() -> bool:
    try:
        with socket.create_connection((_NATS_HOST, _NATS_PORT), timeout=1.0):
            return True
    except OSError:
        return False


needs_nats = pytest.mark.skipif(
    not _nats_reachable(),
    reason=f"no NATS server at {_NATS_HOST}:{_NATS_PORT} (docker run -d -p 4222:4222 nats:alpine)",
)


# ─── NATS: a real broker, and a real subscriber to read back what arrived ────


@needs_nats
def test_points_reach_a_real_broker_on_the_expected_subjects() -> None:
    """Publish through the connector, then read the messages back off the broker.

    Asserting the publisher "did not raise" would prove nothing — a subject typo or
    a payload the broker rejects would pass. The subscriber is the point.
    """
    pytest.importorskip("nats", reason="nats-py not installed — install iaiops[nats]")
    import asyncio

    import nats

    from iaiops.core.egress.nats import NATSPublisher

    prefix = "iaiops-test"
    # The normalized-point shape both sinks consume: ``numeric`` gates a value onto
    # a bus at all (text/state belongs in a historian), and ``metric`` becomes the
    # subject leaf. Getting this wrong silently publishes nothing — which is how the
    # first version of this test "passed" against a real broker with zero messages.
    points = [
        {"metric": "line1.temperature", "value": 21.5, "numeric": True},
        {"metric": "line1.pressure", "value": 4.2, "numeric": True},
    ]
    received: list[tuple[str, dict]] = []
    ready = threading.Event()
    done = threading.Event()

    async def _subscribe() -> None:
        connection = await nats.connect(servers=[f"nats://{_NATS_HOST}:{_NATS_PORT}"])
        try:
            queue: asyncio.Queue = asyncio.Queue()

            async def _handler(msg) -> None:  # noqa: ANN001 — nats' own Msg type
                await queue.put((msg.subject, json.loads(msg.data)))

            await connection.subscribe(f"{prefix}.>", cb=_handler)
            await connection.flush(timeout=5)
            ready.set()
            for _ in range(len(points)):
                received.append(await asyncio.wait_for(queue.get(), timeout=10))
        finally:
            done.set()
            await connection.drain()

    thread = threading.Thread(target=lambda: asyncio.run(_subscribe()), daemon=True)
    thread.start()
    assert ready.wait(timeout=10), "the subscriber never came up"

    published = NATSPublisher(
        servers=f"nats://{_NATS_HOST}:{_NATS_PORT}", subject_prefix=prefix
    ).publish_points(points)
    assert published == len(points)

    assert done.wait(timeout=15), "messages never arrived at the subscriber"
    thread.join(timeout=5)

    by_subject = dict(received)
    assert len(by_subject) == len(points), f"expected {len(points)} messages, got {received}"
    for subject in by_subject:
        assert subject.startswith(f"{prefix}.tag."), f"unexpected subject {subject!r}"
    values = {payload.get("value") for payload in by_subject.values()}
    assert values == {21.5, 4.2}, f"values did not survive the wire: {received}"


@needs_nats
def test_an_event_reaches_the_broker_under_its_own_subject() -> None:
    pytest.importorskip("nats", reason="nats-py not installed")
    import asyncio

    import nats

    from iaiops.core.egress.nats import NATSPublisher

    prefix = "iaiops-test-evt"
    received: list[tuple[str, dict]] = []
    ready = threading.Event()
    done = threading.Event()

    async def _subscribe() -> None:
        connection = await nats.connect(servers=[f"nats://{_NATS_HOST}:{_NATS_PORT}"])
        try:
            queue: asyncio.Queue = asyncio.Queue()

            async def _handler(msg) -> None:  # noqa: ANN001
                await queue.put((msg.subject, json.loads(msg.data)))

            await connection.subscribe(f"{prefix}.>", cb=_handler)
            await connection.flush(timeout=5)
            ready.set()
            received.append(await asyncio.wait_for(queue.get(), timeout=10))
        finally:
            done.set()
            await connection.drain()

    thread = threading.Thread(target=lambda: asyncio.run(_subscribe()), daemon=True)
    thread.start()
    assert ready.wait(timeout=10)

    NATSPublisher(servers=f"nats://{_NATS_HOST}:{_NATS_PORT}", subject_prefix=prefix).publish_event(
        "alarm", {"alid": 9001, "text": "chamber over temperature"}
    )

    assert done.wait(timeout=15), "the event never arrived"
    thread.join(timeout=5)

    subject, payload = received[0]
    assert subject == f"{prefix}.alarm", f"wrong subject: {subject!r}"
    assert payload["alid"] == 9001


@needs_nats
def test_an_unreachable_broker_teaches_rather_than_hanging() -> None:
    """A sealed or misconfigured site must get an actionable error, bounded in time.

    **Both halves are the assertion.** This originally took **120 seconds** to pass:
    nats-py defaults to 60 reconnect attempts at 2s apart, so an unreachable broker
    retried for two minutes while connect_timeout=2 sat there looking
    authoritative. ``stream_publish`` is an MCP tool — that is a two-minute hang on a
    typo'd address, and @governed_tool's timeout_seconds only warns. Found by timing
    this test, not by reading the code.
    """
    import time

    from iaiops.core.egress.base import EgressError
    from iaiops.core.egress.nats import NATSPublisher

    publisher = NATSPublisher(servers="nats://127.0.0.1:1", subject_prefix="x", timeout_s=2)
    started = time.monotonic()
    with pytest.raises(EgressError) as excinfo:
        publisher.publish_points([{"metric": "a", "value": 1, "numeric": True}])
    elapsed = time.monotonic() - started

    assert "127.0.0.1:1" in str(excinfo.value)
    assert elapsed < 15, (
        f"took {elapsed:.0f}s to fail against an unreachable broker — timeout_s is "
        "not bounding the connect"
    )


# ─── InfluxDB: a real HTTP endpoint recording the exact line protocol ────────


class _LineRecorder(BaseHTTPRequestHandler):
    """Captures the InfluxDB write request verbatim."""

    received: list[dict]

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's interface
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()
        parsed = urlparse(self.path)
        self.received.append(
            {
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "headers": dict(self.headers),
                "body": body,
            }
        )
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def influx() -> Iterator[tuple[str, list[dict]]]:
    received: list[dict] = []
    handler = type("_Bound", (_LineRecorder,), {"received": received})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_influx_line_protocol_goes_out_over_real_http(influx) -> None:
    """The bytes that leave the box, recorded by a real HTTP server.

    `test_influxdb_sink.py` replaces the `requests` module wholesale, so it checks
    the string we *intended* to send. This checks what an endpoint receives — path,
    query, auth header and body — which is what an operator debugging a historian
    integration is actually looking at.
    """
    from iaiops.core.sink.influxdb import InfluxDBSink

    url, received = influx
    sink = InfluxDBSink(url=url, bucket="plant", org="acme", token="SUPER-SECRET")
    written = sink.write([{"metric": "line1.temperature", "value": 21.5, "numeric": True}])

    assert written >= 1
    assert received, "nothing reached the HTTP endpoint"
    request = received[0]
    assert "line1" in request["body"] or "temperature" in request["body"], (
        f"the measurement is not in the line protocol: {request['body']!r}"
    )
    assert "21.5" in request["body"], f"the value did not go out: {request['body']!r}"
    assert request["query"].get("bucket") == ["plant"], request["query"]
    assert request["query"].get("org") == ["acme"], request["query"]
    assert "SUPER-SECRET" in request["headers"].get("Authorization", ""), (
        "the token did not reach the Authorization header"
    )


def test_influx_batches_multiple_points_into_one_request(influx) -> None:
    """A per-point request would be a real performance defect at plant scale, and
    the mocked test could not tell the difference."""
    from iaiops.core.sink.influxdb import InfluxDBSink

    url, received = influx
    points = [{"metric": f"tag{i}", "value": float(i), "numeric": True} for i in range(5)]
    InfluxDBSink(url=url, bucket="plant", org="acme", token="t").write(points)

    assert len(received) == 1, f"{len(received)} HTTP requests for 5 points"
    assert len(received[0]["body"].strip().splitlines()) == 5, received[0]["body"]
