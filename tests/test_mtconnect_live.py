"""Live MTConnect round-trip against a REAL HTTP agent — no machine tool.

``test_mtconnect.py`` monkeypatches ``_http_get``, so the XML parsing is genuinely
exercised but **the HTTP layer never runs**. Everything below ``_fetch_xml`` was
therefore unverified: the agent URL built from host/port, the query string for
``/sample``, the streamed body read, and — the part that matters most — two
**security/robustness controls that only exist in the transport**:

* the **DTD/entity guard** (XXE / billion-laughs defense) is applied to the FIRST
  streamed chunk, before the rest of the body is consumed. A mock returning a
  finished string cannot show that it fires early, or at all.
* the **response size cap** refuses a body over ``MAX_RESPONSE_BYTES`` *while
  reading*, never buffering it whole first. Again invisible to a mock.

A control asserted only against a stub is a control you have not tested.

The agent here is a real ``ThreadingHTTPServer`` speaking MTConnect XML over the
ordinary ``requests`` path, driven through the normal ``TargetConfig``. It also
advances a real sequence cursor, so ``mtconnect_stream``'s long-poll — including
the ``instance_changed`` stop that protects against an agent restart invalidating
the held cursor — runs against a server that actually behaves that way.

Needs nothing but ``requests``: no container, no root, no external agent.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("requests", reason="requests not installed — install iaiops[mtconnect]")

from iaiops.connectors.mtconnect import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]

_NS_DEV = "urn:mtconnect.org:MTConnectDevices:1.7"
_NS_STREAMS = "urn:mtconnect.org:MTConnectStreams:1.7"
_NS_ASSETS = "urn:mtconnect.org:MTConnectAssets:1.7"

_ASSETS = f"""<?xml version="1.0"?>
<MTConnectAssets xmlns="{_NS_ASSETS}">
  <Header creationTime="2026-08-01T10:00:00Z" instanceId="1" sender="agent"
          assetCount="2"/>
  <Assets>
    <CuttingTool assetId="T-4711" timestamp="2026-08-01T09:30:00Z" toolId="4711">
      <CuttingToolLifeCycle>
        <ToolLife type="MINUTES" countDirection="UP" limit="120">73</ToolLife>
      </CuttingToolLifeCycle>
    </CuttingTool>
    <Fixture assetId="FIX-2" timestamp="2026-08-01T08:00:00Z"/>
  </Assets>
</MTConnectAssets>"""

_PROBE = f"""<?xml version="1.0"?>
<MTConnectDevices xmlns="{_NS_DEV}">
  <Header creationTime="2026-08-01T10:00:00Z" instanceId="1" sender="agent"/>
  <Devices>
    <Device id="d1" name="VMC1" uuid="VMC1-001">
      <Components>
        <Controller id="ctrl" name="Controller">
          <DataItems>
            <DataItem id="exec" type="EXECUTION" category="EVENT"/>
          </DataItems>
        </Controller>
      </Components>
    </Device>
  </Devices>
</MTConnectDevices>"""


def _streams(observations: list[tuple[int, str]], *, next_seq: int, instance: str) -> str:
    """A Streams document carrying ``(sequence, execution-value)`` events."""
    events = "\n".join(
        f'<Execution dataItemId="exec" timestamp="2026-08-01T10:00:0{i % 10}Z" '
        f'sequence="{seq}">{value}</Execution>'
        for i, (seq, value) in enumerate(observations)
    )
    first = observations[0][0] if observations else next_seq
    last = observations[-1][0] if observations else next_seq
    return f"""<?xml version="1.0"?>
<MTConnectStreams xmlns="{_NS_STREAMS}">
  <Header creationTime="2026-08-01T10:00:01Z" instanceId="{instance}" sender="agent"
          firstSequence="{first}" lastSequence="{last}" nextSequence="{next_seq}"/>
  <Streams>
    <DeviceStream name="VMC1" uuid="VMC1-001">
      <ComponentStream component="Controller" name="Controller" componentId="ctrl">
        <Events>
{events}
        </Events>
      </ComponentStream>
    </DeviceStream>
  </Streams>
</MTConnectStreams>"""


class _AgentState:
    """What the stub agent should do next — mutated by individual tests."""

    def __init__(self) -> None:
        self.instance = "1"
        self.total = 12  # observations the agent's buffer holds, sequences 1..12
        self.serve_doctype = False
        self.doctype_then_oversized = False
        self.oversized = False
        self.status = 200
        self.requests: list[str] = []  # full request lines, for URL assertions
        self.restart_after_polls: int | None = None  # flip instanceId mid-stream
        self.sample_polls = 0


class _Handler(BaseHTTPRequestHandler):
    state: _AgentState

    def log_message(self, *args: object) -> None:  # keep pytest output clean
        pass

    def _send(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's interface
        state = self.state
        state.requests.append(self.path)
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if state.status != 200:
            self._send(b"<error/>", state.status)
            return

        if state.serve_doctype:
            head = (
                b'<?xml version="1.0"?>\n<!DOCTYPE MTConnectStreams [\n'
                b'  <!ENTITY xxe "boom">\n]>\n<MTConnectStreams/>\n'
            )
            # Optionally follow the DOCTYPE with a body past the size cap. That is
            # what distinguishes the first-chunk guard from the full-body one: only
            # an early guard can report the DTD, because the cap would trip first.
            tail = (
                b"<!-- filler -->" * ((ops.MAX_RESPONSE_BYTES // 14) + 1000)
                if state.doctype_then_oversized
                else b"<!-- filler -->" * 2000
            )
            self._send(head + tail)
            return

        if state.oversized:
            head = b'<?xml version="1.0"?><MTConnectStreams>'
            filler = b"<Padding/>" * ((ops.MAX_RESPONSE_BYTES // 10) + 1000)
            self._send(head + filler + b"</MTConnectStreams>")
            return

        if parsed.path.endswith("/probe"):
            self._send(_PROBE.encode())
            return

        if parsed.path.endswith("/assets"):
            self._send(_ASSETS.encode())
            return

        if parsed.path.endswith("/sample"):
            state.sample_polls += 1
            if (
                state.restart_after_polls is not None
                and state.sample_polls > state.restart_after_polls
            ):
                state.instance = "2"  # the agent restarted and renumbered
            start = int(query.get("from", ["1"])[0])
            count = int(query.get("count", ["100"])[0])
            end = min(start + count, state.total + 1)
            observations = [(seq, "ACTIVE") for seq in range(start, end)]
            self._send(_streams(observations, next_seq=end, instance=state.instance).encode())
            return

        # /current
        self._send(
            _streams(
                [(state.total, "ACTIVE")], next_seq=state.total + 1, instance=state.instance
            ).encode()
        )


class _QuietServer(ThreadingHTTPServer):
    """Swallow the broken pipe when the client aborts mid-body.

    That abort is the POINT of two of these tests: the DTD guard and the size cap
    both stop reading partway through, which the server sees as the peer hanging
    up. Letting the default handler print its traceback would make the expected
    outcome look like a failure in the test log.
    """

    def handle_error(self, request: object, client_address: object) -> None:
        pass


@pytest.fixture()
def agent() -> Iterator[tuple[TargetConfig, _AgentState]]:
    state = _AgentState()
    handler = type("_BoundHandler", (_Handler,), {"state": state})
    server = _QuietServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # host/port rather than agent_url on purpose: this is the branch of
        # _agent_base that composes the URL, and it had never been exercised.
        yield (
            TargetConfig(
                name="mtc-live",
                protocol="mtconnect",
                host="127.0.0.1",
                port=server.server_address[1],
            ),
            state,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ─── the ordinary paths, over real HTTP ──────────────────────────────────────


def test_probe_over_real_http(agent: tuple[TargetConfig, _AgentState]) -> None:
    target, state = agent
    out = ops.mtconnect_probe(target)
    assert out["devices"][0]["name"] == "VMC1"
    assert state.requests == ["/probe"], "the agent URL/path was not built as expected"


def test_current_over_real_http(agent: tuple[TargetConfig, _AgentState]) -> None:
    target, _ = agent
    out = ops.mtconnect_current(target)
    assert any(o["value"] == "ACTIVE" for o in out["observations"])


def test_sample_query_string_reaches_the_agent(agent: tuple[TargetConfig, _AgentState]) -> None:
    """``_fetch_xml`` composes ``?from=&count=``. A mock never sees the query, so a
    dropped or misspelled parameter would silently read the wrong window."""
    target, state = agent
    ops.mtconnect_sample(target, from_sequence=3, count=4)
    path = state.requests[-1]
    assert path.startswith("/sample?")
    query = parse_qs(urlparse(path).query)
    assert query["from"] == ["3"] and query["count"] == ["4"]


# ─── the transport-only controls ─────────────────────────────────────────────


def test_dtd_is_refused_from_a_real_response(agent: tuple[TargetConfig, _AgentState]) -> None:
    """XXE / entity-expansion defense, against a server that actually serves a
    DOCTYPE."""
    target, state = agent
    state.serve_doctype = True

    with pytest.raises(ValueError) as excinfo:
        ops.mtconnect_probe(target)

    message = str(excinfo.value)
    assert "DTD" in message or "entity" in message.lower()
    assert "boom" not in message, "the entity body leaked into the error"


def test_dtd_guard_fires_on_the_first_chunk_not_after_the_whole_body(
    agent: tuple[TargetConfig, _AgentState],
) -> None:
    """The guard exists twice — on the first streamed chunk in ``_http_get`` and on
    the full body in ``_fetch_xml``. The test above passes with EITHER present, so
    it does not show the early one works; this one does.

    A DOCTYPE followed by a body past ``MAX_RESPONSE_BYTES`` can only be reported as
    a DTD refusal if the guard ran before the rest was consumed. If only the
    full-body guard existed, the size cap would trip first and we would get the
    wrong error — which is the whole point of guarding early: a hostile agent must
    not be able to make us read megabytes before we notice the DOCTYPE.
    """
    target, state = agent
    state.serve_doctype = True
    state.doctype_then_oversized = True

    with pytest.raises(ValueError) as excinfo:
        ops.mtconnect_probe(target)

    message = str(excinfo.value)
    assert "DTD" in message or "entity" in message.lower(), (
        f"expected the DTD refusal, got: {message!r} — the guard did not run before "
        "the body was consumed"
    )


def test_oversized_response_is_refused_while_reading(
    agent: tuple[TargetConfig, _AgentState],
) -> None:
    """The size cap must refuse a body over the limit. The point of streaming is
    that the whole thing is never buffered first — a mock cannot show this either.
    """
    target, state = agent
    state.oversized = True

    with pytest.raises(ValueError) as excinfo:
        ops.mtconnect_probe(target)

    assert str(ops.MAX_RESPONSE_BYTES) in str(excinfo.value)


def test_http_error_becomes_a_teaching_error(agent: tuple[TargetConfig, _AgentState]) -> None:
    """An agent answering 404/500 must surface something an operator can act on,
    not a fabricated empty document."""
    target, state = agent
    state.status = 503

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 — requests' own error type
        ops.mtconnect_probe(target)
    assert "503" in str(excinfo.value)


# ─── the long-poll, against a server with a real cursor ──────────────────────


def test_stream_advances_the_sequence_cursor_and_stops_when_caught_up(
    agent: tuple[TargetConfig, _AgentState],
) -> None:
    """Multiple real round-trips: the cursor must advance by the header's
    ``nextSequence`` each round and stop once the agent has nothing new."""
    target, state = agent
    out = ops.mtconnect_stream(target, from_sequence=1, count=5, interval_ms=0, duration_s=10)

    assert out["observation_count"] == state.total
    assert out["stopped_reason"] in ("caught_up", "no_progress")
    assert state.sample_polls > 1, "only one poll — the cursor never advanced"

    froms = [parse_qs(urlparse(p).query)["from"][0] for p in state.requests if "from=" in p]
    assert froms == sorted(froms, key=int) and len(set(froms)) == len(froms), (
        f"the cursor did not advance monotonically: {froms}"
    )


def test_stream_stops_when_the_agent_restarts_mid_stream(
    agent: tuple[TargetConfig, _AgentState],
) -> None:
    """An ``instanceId`` change means the agent restarted and renumbered, so the
    held ``from`` cursor now points at unrelated data. Continuing would attribute
    someone else's observations to this run — the stream must stop and say why.
    """
    target, state = agent
    state.total = 500  # enough that the stream is still running when the flip lands
    state.restart_after_polls = 2

    out = ops.mtconnect_stream(target, from_sequence=1, count=5, interval_ms=0, duration_s=10)

    assert out["stopped_reason"] == "instance_changed", (
        f"stream did not notice the restart: {out['stopped_reason']}"
    )
    # It must stop AT the restart, not run on to some other bound: the observations
    # kept are the pre-restart ones only.
    assert out["observation_count"] == 10, (
        "observations from after the renumbering were attributed to this run"
    )


def test_assets_are_fetched_from_the_assets_endpoint_and_parsed(
    agent: tuple[TargetConfig, _AgentState],
) -> None:
    """`/assets` is a third document type with its own namespace and shape.

    The connector's other reads all target Streams or Devices documents; assets
    are neither, and the parse walks for an ``Assets`` container and reads
    attributes off its children rather than off data items. Nothing about that
    was exercised against a real HTTP round-trip — which is also what proves the
    request goes to ``/assets`` rather than to ``/current`` with a query.
    """
    target, state = agent

    out = ops.mtconnect_assets(target)

    assert [request for request in state.requests if request.endswith("/assets")], state.requests
    assert out["asset_count"] == 2, out
    by_id = {asset["asset_id"]: asset for asset in out["assets"]}
    assert set(by_id) == {"T-4711", "FIX-2"}, out
    # The type is the child ELEMENT name, not an attribute — a parse that read
    # some `type=` attribute instead would come back empty here.
    assert by_id["T-4711"]["asset_type"] == "CuttingTool", out
    assert by_id["FIX-2"]["asset_type"] == "Fixture", out
    assert by_id["T-4711"]["timestamp"] == "2026-08-01T09:30:00Z", out
    # The CuttingTool carries nested life-cycle elements. They are children of an
    # asset, not assets, and a walk that recursed into them would surface a
    # `CuttingToolLifeCycle` with no assetId — which is why the id set above is
    # asserted as an equality rather than a subset.
    assert "CuttingToolLifeCycle" not in {asset["asset_type"] for asset in out["assets"]}
