"""OPC-UA against a server from a DIFFERENT stack — the only one that judges us.

Every other OPC-UA test in this repo uses `asyncua` on both ends. That is a real
server, but a misreading inside `asyncua` would satisfy both halves, which is why
vendor interop stayed `待核实` in `docs/VERIFICATION-RECORD.md`.

Microsoft's **opc-plc** is an independent implementation — built on the OPC
Foundation .NET stack, the same stack behind a large share of vendor servers::

    docker run -d --rm --name iaiops-opcplc -p 50000:50000 \\
      mcr.microsoft.com/iotedge/opc-plc:2.12.28 --pn=50000 --autoaccept --unsecuretransport

**This file used to assert that sessions were impossible.** `asyncua` 1.x sent a
`ServerUri` in CreateSession that OPC UA Part 4 §5.6.2 says must be empty unless
the endpoint has a `gatewayServerUri`, and the .NET stack enforces it with
`BadServerUriInvalid` — so browse, read and subscribe could not run at all, and
the test was written to go red the day that changed. It went red on 2026-08-02
when the package moved to `asyncua` 2.x, where the field is opt-in. What follows
is what it was replaced with: the reads themselves, against the independent
stack, which is what makes the OPC-UA row a genuine **2a**.

Not covered here: certificate-trust enforcement and the non-`None` security
policies (`test_opcua_security_thirdparty_live.py`), a real PLC's address space,
and vendor-specific extensions.
"""

from __future__ import annotations

import socket

import pytest

pytest.importorskip("asyncua", reason="asyncua not installed — install iaiops[opcua]")

from iaiops.connectors.opcua import ops  # noqa: E402
from iaiops.connectors.opcua.diagnostics import diagnose_connection  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402
from iaiops.core.runtime.connection import _build_opcua_client  # noqa: E402

pytestmark = [pytest.mark.integration]

_HOST = "127.0.0.1"
_PORT = 50000
_URL = f"opc.tcp://{_HOST}:{_PORT}"

#: Nodes the simulator publishes under its own namespace. Values MOVE (the point
#: of a simulator), so tests assert type and status, never a frozen number.
_FAST_COUNTER = "ns=3;s=FastUInt1"
_SLOW_COUNTER = "ns=3;s=SlowUInt1"
_SPIKE = "ns=3;s=SpikeData"


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
        "mcr.microsoft.com/iotedge/opc-plc:2.12.28 --pn=50000 --autoaccept --unsecuretransport)"
    ),
)


def _target() -> TargetConfig:
    return TargetConfig(name="opcplc", protocol="opcua", endpoint_url=_URL, timeout_s=10)


@needs_opcplc
def test_endpoint_discovery_interoperates_with_the_dotnet_stack() -> None:
    """Hello, OpenSecureChannel and GetEndpoints, judged by an independent stack.

    The assertions are on what the SERVER chose — its application URI and its
    security policies — so a client that invented them would fail.
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
def test_a_session_opens_and_the_server_identifies_itself() -> None:
    """The wall is gone: CreateSession succeeds on the .NET stack.

    `product_name` and `manufacturer` come out of the server's own Server object,
    so this cannot pass without a session that actually read it. Kept as the
    first assertion in the file because this is the exact thing that was
    impossible under `asyncua` 1.x.
    """
    info = ops.server_info(_target())

    assert info["manufacturer"] == "Microsoft", info
    assert "OPC UA PLC" in info["product_name"], info
    assert int(info["namespace_count"]) > 1, info
    assert diagnose_connection(_target())["class"] == "ok"


@needs_opcplc
def test_browse_walks_the_servers_own_address_space() -> None:
    """The address space is the SERVER's, not one we seeded.

    An in-process `asyncua` server only ever contains what the test put there.
    Here the namespaces, the node ids and the folder layout are the simulator's,
    so the browse has to cope with a tree it did not design — including nodes in
    several namespaces and vendor folders it knows nothing about.
    """
    children = ops.browse(_target(), "i=85", depth=1)

    names = {child["browse_name"] for child in children}
    assert "OpcPlc" in names, sorted(names)
    node_ids = {child["node_id"] for child in children}
    assert any(nid.startswith("ns=") for nid in node_ids), node_ids
    assert all(child.get("node_id") for child in children), children


@needs_opcplc
def test_reads_carry_the_servers_types_and_status() -> None:
    """Typed reads off an independent stack, including a batch and a bad node.

    Values move by design, so the assertions are on the type, the status and the
    source timestamp the SERVER stamped — the parts our decode has to get right —
    rather than on a number that would be stale by the next call.
    """
    target = _target()

    counter = ops.read_node(target, _FAST_COUNTER)
    assert counter["good"] is True, counter
    assert counter["datatype"] == "UInt32", counter
    assert isinstance(counter["value"], int), counter
    assert counter["status_code"] == "Good", counter
    assert counter["source_timestamp"], counter

    spike = ops.read_node(target, _SPIKE)
    assert spike["datatype"] == "Double", spike
    assert isinstance(spike["value"], float), spike

    batch = ops.read_many(target, [_FAST_COUNTER, _SLOW_COUNTER])
    assert len(batch) == 2, batch
    assert all(isinstance(item["value"], int) for item in batch), batch


@needs_opcplc
def test_an_unknown_node_gets_the_servers_own_refusal() -> None:
    """A node id the server does not have must come back as ITS error, not ours.

    The in-process `asyncua` tests can only show `asyncua` refusing; this is the
    .NET stack's `BadNodeIdUnknown` travelling the wire and being surfaced as a
    readable error rather than an exception or a fabricated value.
    """
    result = ops.read_node(_target(), "ns=3;s=NoSuchNodeAnywhere")

    assert "error" in result, result
    assert "does not exist" in result["error"].lower(), result
    assert "value" not in result or result.get("value") is None, result
