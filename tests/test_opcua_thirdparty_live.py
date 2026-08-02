"""OPC-UA against a server from a DIFFERENT stack — and what that turned up.

Every other OPC-UA test in this repo uses `asyncua` on both ends. That is a real
server, but a misreading inside `asyncua` would satisfy both halves, so vendor
interop stayed `待核实` in `docs/VERIFICATION-RECORD.md`.

Microsoft's **opc-plc** is an independent implementation — it is built on the OPC
Foundation .NET stack, the same stack behind a large share of vendor servers::

    docker run -d --rm --name iaiops-opcplc -p 50000:50000 \\
      mcr.microsoft.com/iotedge/opc-plc:latest --pn=50000 --autoaccept --unsecuretransport

Pointing the connector at it found something the `asyncua`-on-both-ends tests
never could: **`asyncua` 1.x cannot open a session on that stack at all.** It
sends a `ServerUri` in CreateSession; OPC UA Part 4 §5.6.2 says that field is
only set when the endpoint has a `gatewayServerUri`, and the .NET stack enforces
the rule with `BadServerUriInvalid`. `asyncua` 2.x makes the field opt-in
(`Client.server_uri`, default `None`) — this package is pinned `<2`.

So the honest state, recorded rather than glossed:

* transport, secure channel and endpoint discovery **do** interoperate — proven
  below against the .NET stack;
* sessions (browse, read, subscribe) **do not**, for a reason that is entirely
  client-side and needs an `asyncua` 2.x migration, not a site change;
* `opcua_diagnose_connection` now says exactly that instead of "unknown".

**When the session test starts failing, that is the good news** — it means the
client stopped sending ServerUri, and both this file and the record need
updating rather than the test.
"""

from __future__ import annotations

import socket

import pytest

pytest.importorskip("asyncua", reason="asyncua not installed — install iaiops[opcua]")

from iaiops.connectors.opcua.diagnostics import diagnose_connection  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402
from iaiops.core.runtime.connection import _build_opcua_client  # noqa: E402

pytestmark = [pytest.mark.integration]

_HOST = "127.0.0.1"
_PORT = 50000
_URL = f"opc.tcp://{_HOST}:{_PORT}"


def _reachable() -> bool:
    try:
        with socket.create_connection((_HOST, _PORT), timeout=1.0):
            return True
    except OSError:
        return False


needs_opcplc = pytest.mark.skipif(
    not _reachable(),
    reason=(
        f"no third-party OPC-UA server at {_HOST}:{_PORT} (docker run -d -p 50000:50000 "
        "mcr.microsoft.com/iotedge/opc-plc:latest --pn=50000 --autoaccept --unsecuretransport)"
    ),
)


def _target() -> TargetConfig:
    return TargetConfig(name="opcplc", protocol="opcua", endpoint_url=_URL, timeout_s=10)


@needs_opcplc
def test_endpoint_discovery_interoperates_with_the_dotnet_stack() -> None:
    """Hello, OpenSecureChannel and GetEndpoints, judged by an independent stack.

    This is the part that works, and it is not nothing: the binary protocol
    handshake and the endpoint descriptions are parsed by a server nobody here
    wrote, in a language nobody here used. The assertions are on what the SERVER
    chose — its application URI and its security policies — so a client that
    invented them would fail.
    """
    client = _build_opcua_client(_target())
    try:
        endpoints = client.connect_and_get_server_endpoints()
    finally:
        client.disconnect()

    assert endpoints, "the third-party server returned no endpoints"
    application_uris = {endpoint.Server.ApplicationUri for endpoint in endpoints}
    assert any("OpcPlc" in uri for uri in application_uris), application_uris
    policies = {endpoint.SecurityPolicyUri.rsplit("#", 1)[-1] for endpoint in endpoints}
    assert "Basic256Sha256" in policies, policies


@needs_opcplc
def test_a_session_is_refused_and_the_diagnosis_says_why() -> None:
    """The interop gap, pinned — including the verdict an operator gets.

    Before this, `opcua_diagnose_connection` answered `unknown` with "inspect the
    detail", for a failure that is precise, client-side and unfixable at the
    site. The tool whose entire purpose is classifying failed connections has to
    do better than that on a failure this specific.

    If this ever comes back `ok`, the ServerUri behaviour changed: delete the
    `client_interop` rule's asyncua-1.x wording, move the OPC-UA row in
    docs/VERIFICATION-RECORD.md up, and celebrate.
    """
    verdict = diagnose_connection(_target())

    assert verdict["class"] == "client_interop", verdict
    assert verdict["reachable"] is False
    assert "ServerUri" in verdict["detail"] or "ServerUri" in verdict["diagnosis"], verdict
    # The remediation has to name the cause AND absolve the site, or the operator
    # goes looking for a firewall that is not there.
    assert "asyncua" in verdict["remediation"], verdict
