"""Certificate TRUST against a third-party stack — enforced, not merely offered.

`test_opcua_security.py` proves the connector negotiates Basic256Sha256 and reads
over an encrypted channel. What it cannot prove is that trust *gates* anything:
its server is an in-process `asyncua` one running the permissive validator, which
accepts any client certificate. So "the server rejected this client's
certificate" — a whole verdict class in `diagnostics.py`, with the remediation an
operator would follow — had never been produced by a server that actually
enforces it.

Microsoft's opc-plc without `--autoaccept` is a real OPC Foundation .NET stack
with a real directory trust store. This file walks the provisioning path an
operator walks::

    scripts/opcua_cert_harness.sh uv run --no-sync pytest tests/test_opcua_cert_trust_live.py -q -rs

1. connect with a self-signed client certificate the server has never seen →
   refused, and the server files it under `pki/rejected`;
2. move that certificate into `pki/trusted/certs` — exactly what "add this client
   to the server's trusted store" means;
3. the same connection now opens, and a read comes back over the encrypted
   channel.

**A finding worth carrying:** the .NET stack also enforces that the certificate's
SAN URI equals the ApplicationUri the client announces, and refuses with
`BadCertificateUriInvalid` when it does not. `asyncua`'s own server does not check
that, so a certificate minted against an in-house test server can be trusted by a
vendor server and still be refused. The fixture below therefore mints the
certificate with `asyncua`'s client ApplicationUri, which is what a site would
have to do too.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("asyncua", reason="asyncua not installed — install iaiops[opcua]")

from iaiops.connectors.opcua import ops  # noqa: E402
from iaiops.connectors.opcua.diagnostics import diagnose_connection  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]

STRICT_URL = os.environ.get("IAIOPS_OPCUA_STRICT_URL", "")
PKI_DIR = os.environ.get("IAIOPS_OPCUA_PKI", "")
TRUST_CMD = os.environ.get("IAIOPS_OPCUA_TRUST_CMD", "")

#: The ApplicationUri asyncua's client announces. The certificate's SAN URI must
#: match it or a .NET-stack server refuses with BadCertificateUriInvalid — see the
#: module docstring.
_CLIENT_APP_URI = "urn:example.org:FreeOpcUa:opcua-asyncio"

needs_strict_server = pytest.mark.skipif(
    not (STRICT_URL and PKI_DIR and TRUST_CMD),
    reason=(
        "live OPC-UA cert trust needs a strict server, its PKI store and a trust "
        "command (IAIOPS_OPCUA_STRICT_URL + IAIOPS_OPCUA_PKI + IAIOPS_OPCUA_TRUST_CMD); "
        "run scripts/opcua_cert_harness.sh"
    ),
)


@pytest.fixture
def client_cert(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """A fresh self-signed client certificate the server has never seen.

    Fresh per test on purpose: a certificate reused from an earlier run could
    already be in the trust store, and the refusal half would pass for the wrong
    reason.
    """
    from asyncua.crypto.cert_gen import setup_self_signed_certificate
    from cryptography.x509.oid import ExtendedKeyUsageOID

    key, cert = tmp_path / "client_key.pem", tmp_path / "client_cert.der"
    asyncio.run(
        setup_self_signed_certificate(
            key,
            cert,
            _CLIENT_APP_URI,
            "127.0.0.1",
            [ExtendedKeyUsageOID.CLIENT_AUTH],
            {"countryName": "CN", "organizationName": "iaiops-cert-trust-test"},
        )
    )
    yield key, cert


def _target(key: Path, cert: Path) -> TargetConfig:
    return TargetConfig(
        name="strict-opcua",
        protocol="opcua",
        endpoint_url=STRICT_URL,
        timeout_s=10,
        client_cert=str(cert),
        client_key=str(key),
        security_policy="Basic256Sha256",
        security_mode="SignAndEncrypt",
    )


def _wait_for_rejected() -> list[Path]:
    """Wait for the server to file the certificate it refused (bounded).

    It writes that file AFTER answering the client, so anything that runs the
    instant `diagnose_connection` returns finds an empty store.
    """
    rejected = Path(PKI_DIR) / "rejected" / "certs"
    deadline = time.monotonic() + 10
    while not list(rejected.glob("*.der")) and time.monotonic() < deadline:
        time.sleep(0.2)
    return list(rejected.glob("*.der"))


def _promote_rejected() -> None:
    """Promote what the server rejected into its trusted store.

    Runs the harness's script rather than copying files here, and that is not
    fastidiousness: the promotion has to be performed BY A PROCESS INSIDE THE
    SERVER'S OWN FILESYSTEM. Writing the identical file from the host across a
    macOS bind mount leaves the session refused (measured: still refused 30s
    later), while the same copy made inside the container is honoured on the very
    next connect. Reading the store from the host works, which is why the tests
    can still watch the rejected certificate appear.

    Two other things this gesture has to get right, both found the slow way:
    the file must be THE ONE THE SERVER WROTE (a .NET directory store indexes by
    the `<subject> [<thumbprint>].der` name it assigns), and the certificate must
    already have been rejected once, or there is nothing to promote.
    """
    assert _wait_for_rejected(), f"the server filed no rejected certificate in {PKI_DIR}"
    subprocess.run([TRUST_CMD], check=True, capture_output=True)  # noqa: S603 — fixed argv


@needs_strict_server
def test_an_untrusted_certificate_is_refused_and_diagnosed(client_cert) -> None:
    """The `certificate` verdict, produced by a server that enforces trust.

    Until now that class could only be produced by a hand-written exception
    string in a unit test. The remediation it carries — "add this client's
    certificate to the server's trusted-clients store" — is asserted here
    because the next test proves it is the instruction that works.
    """
    key, cert = client_cert

    verdict = diagnose_connection(_target(key, cert))

    assert verdict["class"] == "certificate", verdict
    assert verdict["reachable"] is False
    assert "trust" in verdict["remediation"].lower(), verdict
    # The server files the certificate it refused, which is where an operator
    # finds it to promote — the reason the remediation is actionable at all.
    assert _wait_for_rejected(), f"the server did not file the rejected certificate: {PKI_DIR}"


@needs_strict_server
def test_trusting_the_certificate_opens_the_encrypted_session(client_cert) -> None:
    """Follow the remediation, and the same connection works.

    This is the half that makes the refusal meaningful: the *only* thing that
    changed between the two connects is which directory the certificate sits in.
    The read at the end travels over Basic256Sha256 SignAndEncrypt, and the value
    is the server's own identity, so it cannot come from anywhere else.
    """
    key, cert = client_cert
    target = _target(key, cert)
    assert diagnose_connection(target)["class"] == "certificate", "cert was already trusted"

    _promote_rejected()

    verdict = diagnose_connection(target)
    assert verdict["class"] == "ok", verdict
    assert verdict["reachable"] is True

    info = ops.server_info(target)
    assert info["manufacturer"] == "Microsoft", info
    assert "OPC UA PLC" in info["product_name"], info


@needs_strict_server
def test_a_certificate_whose_uri_does_not_match_is_refused_even_when_trusted(
    tmp_path: Path,
) -> None:
    """Trust is necessary, not sufficient: the SAN URI must match too.

    The .NET stack checks the certificate's SAN URI against the ApplicationUri
    the client announced and answers `BadCertificateUriInvalid`. `asyncua`'s own
    server does not, so this is a rejection no in-process test could produce —
    and a real one to hit at a site, because a certificate minted for a different
    application name looks perfectly valid until a vendor server sees it.
    """
    from asyncua.crypto.cert_gen import setup_self_signed_certificate
    from cryptography.x509.oid import ExtendedKeyUsageOID

    key, cert = tmp_path / "wrong_key.pem", tmp_path / "wrong_cert.der"
    asyncio.run(
        setup_self_signed_certificate(
            key,
            cert,
            "urn:iaiops:some:other:application",  # NOT what the client announces
            "127.0.0.1",
            [ExtendedKeyUsageOID.CLIENT_AUTH],
            {"countryName": "CN", "organizationName": "iaiops-cert-trust-test"},
        )
    )
    # Get it refused first so the server files it, then promote that exact file:
    # the certificate ends up genuinely trusted, and is still refused.
    assert diagnose_connection(_target(key, cert))["class"] == "certificate"
    _promote_rejected()

    verdict = diagnose_connection(_target(key, cert))

    assert verdict["class"] == "certificate", verdict
    assert verdict["reachable"] is False
