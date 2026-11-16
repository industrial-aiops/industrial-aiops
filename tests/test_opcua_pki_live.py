"""Local strict CA-chain/CRL fixture; not vendor PKI or production CRL validation."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("asyncua")
from asyncua import Server, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.crypto.truststore import TrustStore
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from iaiops.connectors.opcua.diagnostics import diagnose_connection
from iaiops.core.runtime.config import TargetConfig

pytestmark = pytest.mark.integration
URI = "urn:example.org:FreeOpcUa:opcua-asyncio"


def issue(name, key, issuer=None, issuer_key=None, *, ca=False, expired=False, uri=URI):
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=3))
        .not_valid_after(now + timedelta(days=-1 if expired else 3))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(x509.KeyUsage(True, True, True, True, False, ca, ca, None, None), True)
    )
    if issuer_key:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), False
        )
    if not ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.UniformResourceIdentifier(uri), x509.DNSName("localhost")]
            ),
            False,
        ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), False)
    return builder.sign(issuer_key or key, hashes.SHA256())


@pytest.mark.parametrize("case", ["valid", "missing_issuer", "revoked", "expired", "wrong_uri"])
def test_ca_chain_and_crl_gate_encrypted_connector_session(tmp_path, case):
    async def run():
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root = issue("Root", root_key, ca=True)
        issuer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        issuer = issue("Issuer", issuer_key, root, root_key, ca=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = issue(
            "Client",
            key,
            issuer,
            issuer_key,
            expired=case == "expired",
            uri="urn:wrong" if case == "wrong_uri" else URI,
        )
        trust = tmp_path / "trusted"
        crls = tmp_path / "crls"
        trust.mkdir()
        crls.mkdir()
        (trust / "root.der").write_bytes(root.public_bytes(serialization.Encoding.DER))
        if case != "missing_issuer":
            (trust / "issuer.der").write_bytes(issuer.public_bytes(serialization.Encoding.DER))
        now = datetime.now(UTC)
        crl = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(issuer.subject)
            .last_update(now - timedelta(minutes=1))
            .next_update(now + timedelta(days=1))
        )
        if case == "revoked":
            crl = crl.add_revoked_certificate(
                x509.RevokedCertificateBuilder()
                .serial_number(leaf.serial_number)
                .revocation_date(now - timedelta(seconds=10))
                .build()
            )
        (crls / "issuer.der").write_bytes(
            crl.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)
        )
        store = TrustStore([trust], [crls])
        await store.load()
        validator = CertificateValidator(
            CertificateValidatorOptions.TRUSTED
            | CertificateValidatorOptions.REVOKED
            | CertificateValidatorOptions.TIME_RANGE
            | CertificateValidatorOptions.URI
            | CertificateValidatorOptions.PEER_CLIENT,
            store,
        )
        failures = []

        async def validate(cert, app):
            try:
                await validator.validate(cert, app)
            except Exception as exc:
                failures.append(getattr(exc, "code", None))
                raise

        client_cert, client_key = tmp_path / "client.der", tmp_path / "client.pem"
        client_cert.write_bytes(leaf.public_bytes(serialization.Encoding.DER))
        client_key.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        client_key.chmod(0o600)
        server_cert, server_key = tmp_path / "server.der", tmp_path / "server.pem"
        await setup_self_signed_certificate(
            server_key,
            server_cert,
            "urn:freeopcua:python:server",
            "localhost",
            [ExtendedKeyUsageOID.SERVER_AUTH],
            {"organizationName": "iaiops-local-pki-test"},
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = Server()
        await server.init()
        url = f"opc.tcp://127.0.0.1:{port}/pki"
        server.set_endpoint(url)
        server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
        await server.load_certificate(server_cert)
        await server.load_private_key(server_key)
        server.set_certificate_validator(validate)
        target = TargetConfig(
            name="pki-fixture",
            protocol="opcua",
            endpoint_url=url,
            security_policy="Basic256Sha256",
            security_mode="SignAndEncrypt",
            client_cert=str(client_cert),
            client_key=str(client_key),
            timeout_s=5,
        )
        async with server:
            verdict = await asyncio.to_thread(diagnose_connection, target)
        if case == "valid":
            assert verdict["reachable"] is True, verdict
            assert not failures
        else:
            assert verdict["reachable"] is False, verdict
            expected = {
                "missing_issuer": "BadCertificateUntrusted",
                "revoked": "BadCertificateRevoked",
                "expired": "BadCertificateTimeInvalid",
                "wrong_uri": "BadCertificateUriInvalid",
            }[case]
            assert getattr(ua.StatusCodes, expected) in failures, failures

    asyncio.run(run())
