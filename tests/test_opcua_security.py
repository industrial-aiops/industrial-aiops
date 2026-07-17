"""End-to-end tests for OPC-UA certificate message security (Sign / SignAndEncrypt).

Where ``test_mtls.py`` asserts the security STRING is applied to a *fake* client,
this drives a REAL in-process ``asyncua.sync.Server`` that accepts ONLY
Basic256Sha256 secure channels (no anonymous / no-security endpoint). Self-signed
application certificates are generated with asyncua's own ``cert_gen`` helper, and
the ops layer reads over the encrypted channel — proving cert security works
against a live server, not merely that config is wired.

Because the secure server offers *no* unsecured endpoint, any successful read here
is proof the traffic went over the negotiated secure channel; one test also
introspects the connected client to assert the policy URI and message-security
mode directly. A separate plain (anonymous) server guards the back-compat path:
a target with no client cert still connects anonymously, unchanged.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

from iaiops.connectors.opcua import ops
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import OTConnectionError, opcua_session

# asyncua's built-in default ApplicationUri for its server and (sync) client.
# Matching each cert's SAN URI to these keeps the in-process handshake quiet; a
# mismatch would only log a cosmetic "application uri" warning (our server runs
# the default permissive validator), never fail the connection.
_SERVER_APP_URI = "urn:freeopcua:python:server"
_CLIENT_APP_URI = "urn:example.org:FreeOpcUa:opcua-asyncio"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_self_signed(key_file: Path, cert_file: Path, app_uri: str) -> None:
    """Generate an OPC-UA application cert/key pair (SAN URI + client/server EKU).

    ``setup_self_signed_certificate`` is a coroutine; the fixtures are sync, so it
    is driven with ``asyncio.run`` (no event loop is running under a sync test).
    """
    from asyncua.crypto.cert_gen import setup_self_signed_certificate
    from cryptography.x509.oid import ExtendedKeyUsageOID

    asyncio.run(
        setup_self_signed_certificate(
            key_file,
            cert_file,
            app_uri,
            "127.0.0.1",
            [ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH],
            {"countryName": "CN", "organizationName": "iaiops-test"},
        )
    )


@pytest.fixture(scope="module")
def secure_opcua_server(tmp_path_factory):
    """Start a real in-process OPC-UA server that ONLY accepts Basic256Sha256.

    Both Sign and SignAndEncrypt are offered (so one server exercises both modes),
    and no anonymous / no-security endpoint is published. Yields the endpoint URL,
    a node id, and the client cert/key + server cert paths.
    """
    pytest.importorskip("asyncua.sync")
    from asyncua import ua
    from asyncua.sync import Server

    certs = tmp_path_factory.mktemp("opcua_certs")
    server_key = certs / "server_key.pem"
    server_cert = certs / "server_cert.der"
    client_key = certs / "client_key.pem"
    client_cert = certs / "client_cert.der"
    _write_self_signed(server_key, server_cert, _SERVER_APP_URI)
    _write_self_signed(client_key, client_cert, _CLIENT_APP_URI)

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/aiops"
    srv = Server()
    srv.set_endpoint(url)
    srv.set_server_name("iaiops-security-test")
    # Offer ONLY encrypted channels — with no unsecured endpoint, a successful
    # read proves the traffic used the negotiated secure channel.
    srv.set_security_policy(
        [
            ua.SecurityPolicyType.Basic256Sha256_Sign,
            ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
        ]
    )
    srv.load_certificate(str(server_cert))
    srv.load_private_key(str(server_key))
    idx = srv.register_namespace("http://aiops.test")
    line = srv.nodes.objects.add_folder(idx, "Line1")
    temp = line.add_variable(idx, "Temperature", 85.0)
    srv.start()
    try:
        yield {
            "url": url,
            "temp": temp.nodeid.to_string(),
            "client_cert": str(client_cert),
            "client_key": str(client_key),
            "server_cert": str(server_cert),
        }
    finally:
        srv.stop()


@pytest.fixture(scope="module")
def plain_opcua_server():
    """Start a real in-process OPC-UA server with NO security (anonymous).

    Guards the back-compat path: a target with no client cert must keep using the
    unchanged anonymous connection.
    """
    pytest.importorskip("asyncua.sync")
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/plain"
    srv = Server()
    srv.set_endpoint(url)
    srv.set_server_name("iaiops-plain-test")
    idx = srv.register_namespace("http://aiops.test")
    line = srv.nodes.objects.add_folder(idx, "Line1")
    temp = line.add_variable(idx, "Temperature", 42.0)
    srv.start()
    try:
        yield {"url": url, "temp": temp.nodeid.to_string()}
    finally:
        srv.stop()


def _secure_target(
    server: dict, *, mode: str = "SignAndEncrypt", with_server_cert: bool = True
) -> TargetConfig:
    """Build a cert-secured OPC-UA target for the in-process secure server."""
    return TargetConfig(
        name="secure-line",
        protocol="opcua",
        endpoint_url=server["url"],
        security_policy="Basic256Sha256",
        security_mode=mode,
        client_cert=server["client_cert"],
        client_key=server["client_key"],
        server_cert=server["server_cert"] if with_server_cert else "",
    )


@pytest.mark.integration
def test_sign_and_encrypt_channel_is_negotiated(secure_opcua_server):
    """The live session negotiates a real Basic256Sha256 SignAndEncrypt channel."""
    from asyncua import ua

    target = _secure_target(secure_opcua_server, mode="SignAndEncrypt")
    with opcua_session(target) as client:
        policy = client.aio_obj.security_policy
        assert "Basic256Sha256" in policy.URI
        assert policy.Mode == ua.MessageSecurityMode.SignAndEncrypt


@pytest.mark.integration
def test_server_info_over_encrypted_channel(secure_opcua_server):
    info = ops.server_info(_secure_target(secure_opcua_server))
    assert info["state"] == 0
    assert any("aiops.test" in n for n in info["namespaces"])


@pytest.mark.integration
def test_read_node_over_encrypted_channel(secure_opcua_server):
    r = ops.read_node(_secure_target(secure_opcua_server), secure_opcua_server["temp"])
    assert r["value"] == 85.0
    assert r["datatype"] == "Double"
    assert r["good"] is True
    assert "error" not in r


@pytest.mark.integration
def test_browse_over_encrypted_channel(secure_opcua_server):
    nodes = ops.browse(_secure_target(secure_opcua_server), node_id="i=85", depth=2)
    names = {n["browse_name"] for n in nodes}
    assert "Line1" in names
    assert "Temperature" in names


@pytest.mark.integration
def test_sign_only_channel_reads(secure_opcua_server):
    """Sign (integrity, no encryption) is a distinct mode; it too reads end-to-end."""
    from asyncua import ua

    target = _secure_target(secure_opcua_server, mode="Sign")
    with opcua_session(target) as client:
        assert client.aio_obj.security_policy.Mode == ua.MessageSecurityMode.Sign
    r = ops.read_node(target, secure_opcua_server["temp"])
    assert r["value"] == 85.0
    assert r["good"] is True


@pytest.mark.integration
def test_server_certificate_autodiscovered(secure_opcua_server):
    """With no server_cert configured, the client discovers it during connect."""
    target = _secure_target(secure_opcua_server, with_server_cert=False)
    info = ops.server_info(target)
    assert info["state"] == 0
    r = ops.read_node(target, secure_opcua_server["temp"])
    assert r["value"] == 85.0


@pytest.mark.integration
def test_anonymous_rejected_on_secure_only_server(secure_opcua_server):
    """A no-cert (anonymous) target cannot reach a secure-only server."""
    bare = TargetConfig(name="bare", protocol="opcua", endpoint_url=secure_opcua_server["url"])
    with pytest.raises(OTConnectionError):
        ops.server_info(bare)


@pytest.mark.integration
def test_no_cert_target_stays_anonymous(plain_opcua_server):
    """Back-compat: a target with no client cert uses the anonymous path unchanged."""
    target = TargetConfig(
        name="plain-line", protocol="opcua", endpoint_url=plain_opcua_server["url"]
    )
    r = ops.read_node(target, plain_opcua_server["temp"])
    assert r["value"] == 42.0
    assert r["good"] is True
