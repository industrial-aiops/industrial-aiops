"""GetEndpoints against a REAL asyncua server — shape, and the thread-leak check.

The unit tests drive ``opcua_endpoints`` through a fake whose attribute names I
chose, which is precisely the arrangement where a fake and its parser agree and
are both wrong. This file checks the parser against objects asyncua actually
builds: ``EndpointDescription.SecurityPolicyUri`` really does carry the
``#None`` fragment, ``SecurityMode`` really is an enum whose value is an int,
``Server.ApplicationName`` really is a ``LocalizedText`` needing ``.Text``, and
``UserIdentityTokens`` really are ``UserTokenPolicy`` objects.

The other half is the one a fake cannot show at all: asyncua's sync ``Client``
starts a NON-DAEMON ThreadLoop in its constructor, so a probe that forgets to
disconnect leaks a thread every time. A scanner sweeping a subnet would
accumulate one per host and then never exit. Here the same endpoint is probed
repeatedly and the thread count has to come back.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

pytest.importorskip("asyncua", reason="asyncua not installed — install iaiops[opcua]")

from iaiops.connectors.opcua import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402
from iaiops.core.runtime.connection import OTConnectionError  # noqa: E402

pytestmark = [pytest.mark.integration]

_SERVER_NAME = "iaiops-endpoints-test"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_target():
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/iaiops-endpoints/"
    server = Server()
    server.set_endpoint(url)
    server.set_server_name(_SERVER_NAME)
    server.start()
    try:
        yield TargetConfig(name="live-endpoints", protocol="opcua", endpoint_url=url, timeout_s=4)
    finally:
        server.stop()


def test_endpoints_parse_against_a_real_server(live_target: TargetConfig) -> None:
    """Every field this function promises, read off objects asyncua built."""
    out = ops.opcua_endpoints(live_target)

    assert out["endpoint_count"] >= 1
    assert out["application_name"] == _SERVER_NAME, (
        "ApplicationName is a LocalizedText — reading it without .Text yields a repr"
    )
    assert out["application_uri"].startswith("urn:"), out["application_uri"]
    assert out["product_uri"], "ProductUri came back empty against a real server"

    row = out["endpoints"][0]
    assert row["url"].startswith("opc.tcp://")
    # The real URI is '...SecurityPolicy#None'; a parser that did not shorten it
    # would put the whole URI in an inventory column.
    assert "#" not in row["security_policy"]
    assert row["security_policy"] == "None"
    assert row["security_mode"] in {"None", "Sign", "SignAndEncrypt"}
    assert isinstance(row["security_level"], int)
    assert "Anonymous" in row["user_tokens"]


def test_an_unsecured_server_is_flagged_for_what_it_is(live_target: TargetConfig) -> None:
    """A default asyncua server offers SecurityPolicy None with Anonymous tokens.
    That is exactly the finding a 62443 review acts on, and it is visible here
    without authenticating — so the booleans must not soften it."""
    out = ops.opcua_endpoints(live_target)
    assert out["allows_none_security"] is True
    assert out["allows_anonymous"] is True


def test_repeated_probes_leak_no_threads(live_target: TargetConfig) -> None:
    """The failure a fake cannot show.

    asyncua's sync Client starts a non-daemon ThreadLoop in its CONSTRUCTOR, and
    only ``disconnect`` stops it. A scanner probing a /24 would otherwise finish
    with 254 live threads and never exit.
    """
    ops.opcua_endpoints(live_target)  # warm up: first call may create pooled threads
    time.sleep(0.3)
    baseline = threading.active_count()

    for _ in range(5):
        ops.opcua_endpoints(live_target)
    time.sleep(0.5)

    grown = threading.active_count() - baseline
    assert grown <= 1, (
        f"thread count grew by {grown} over 5 probes (baseline {baseline}) — "
        "the ThreadLoop is not being released"
    )


def test_a_dead_endpoint_fails_fast_and_leaks_no_threads() -> None:
    """The leak path that actually bites: an unreachable host. The ThreadLoop is
    already running by the time the connect fails, so the teardown has to happen
    on the error path too."""
    port = _free_port()  # bound then released — nothing is listening
    target = TargetConfig(
        name="dead",
        protocol="opcua",
        endpoint_url=f"opc.tcp://127.0.0.1:{port}/nothing/",
        timeout_s=2,
    )
    time.sleep(0.2)
    baseline = threading.active_count()

    for _ in range(3):
        with pytest.raises(OTConnectionError):
            ops.opcua_endpoints(target)
    time.sleep(0.5)

    grown = threading.active_count() - baseline
    assert grown <= 1, (
        f"thread count grew by {grown} over 3 FAILED probes (baseline {baseline}) — "
        "the error path is not releasing the ThreadLoop"
    )


def test_identification_does_not_consume_a_session(live_target: TargetConfig) -> None:
    """The reason this function exists. Embedded servers allow only two to five
    sessions; if identification took one, an unattended re-scan would evict the
    plant's real SCADA client.

    Checked by opening MORE identifications back to back than a small server would
    have session slots for, then confirming a genuine session can still be opened
    afterwards.
    """
    for _ in range(8):
        ops.opcua_endpoints(live_target)

    # A real session must still be available — nothing was held.
    info = ops.server_info(live_target)
    assert info["product_name"] or info["manufacturer"]
