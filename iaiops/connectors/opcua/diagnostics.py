"""OPC-UA connection self-diagnosis (READ-ONLY).

"OPC-UA won't connect" is the single most-reported OPC-UA pain: the failure is
almost always one of a handful of classes, but servers surface it as an opaque
``Bad_SecurityChecksFailed`` / socket error / stack trace. This turns a failed
connect into a *classified, actionable verdict* — what went wrong and the exact
next step — instead of a raw error. Complements the connection layer's
``_translate_opcua`` (which only raises 3 buckets) with cert-trust and
security-policy classification.

It attempts a real connect (no writes) and disconnects immediately.
"""

from __future__ import annotations

import socket
from typing import Any

from iaiops.core.governance import sanitize
from iaiops.core.runtime.connection import OTConnectionError, _build_opcua_client

# Ordered classifier. Each entry: (predicate(name, detail, exc), class, diagnosis,
# remediation). First match wins, so order most-specific → most-generic.
_RULES: list[tuple[Any, str, str, str]] = [
    (
        lambda n, d, e: "certificateuntrusted" in d or "securitychecksfailed" in d
        or "badcertificate" in n.lower() or "certificate" in d,
        "certificate",
        "The server rejected this client's certificate (not in its trust list).",
        "Add this client's certificate to the server's trusted-clients store, or "
        "bootstrap with SecurityPolicy=None to connect first, then provision trust.",
    ),
    (
        lambda n, d, e: "useraccessdenied" in d or "identitytoken" in d
        or "baduseraccess" in n.lower(),
        "auth",
        "Authentication was rejected (bad user/password or required identity).",
        "Check the username and the stored password (see 'iaiops doctor'); the "
        "server may require a user or a certificate identity rather than anonymous.",
    ),
    (
        lambda n, d, e: "securitypolicy" in d or "policyid" in d
        or "securechannel" in d or "connectionrejected" in d,
        "security_policy",
        "Security policy / message-security-mode mismatch with the server endpoint.",
        "Match the endpoint's SecurityPolicy and mode (e.g. the server requires "
        "Basic256Sha256 Sign&Encrypt while the client offered None, or vice versa).",
    ),
    (
        lambda n, d, e: isinstance(e, ConnectionRefusedError) or "refused" in d,
        "port_closed",
        "Connection refused — nothing is listening on that host:port.",
        "Verify the port (OPC-UA default 4840) and that the server process is up; "
        "check the endpoint_url path after the port.",
    ),
    (
        lambda n, d, e: isinstance(e, socket.gaierror) or "getaddrinfo" in d
        or "name or service not known" in d or "nodename nor servname" in d,
        "dns",
        "The host name in endpoint_url did not resolve.",
        "Fix the hostname/IP in endpoint_url (opc.tcp://HOST:4840), or add a DNS / "
        "hosts entry the gateway can resolve.",
    ),
    (
        lambda n, d, e: isinstance(e, TimeoutError) or "timed out" in d or "timeout" in n.lower(),
        "firewall_timeout",
        "No response before timeout — a firewall is likely dropping the connection.",
        "Open the OPC-UA port through OT/DMZ firewalls and confirm the host is "
        "reachable from where this tap runs (it should sit in the DMZ / IT side).",
    ),
    (
        lambda n, d, e: isinstance(e, (ConnectionError, OSError)),
        "unreachable",
        "Host unreachable at the network layer.",
        "Check IP/route/VLAN and OT segmentation between this tap and the endpoint.",
    ),
]


def _verdict(cls: str, endpoint: str, diagnosis: str, remediation: str, detail: str = "") -> dict:
    return {
        "endpoint": sanitize(endpoint, 200),
        "reachable": cls == "ok",
        "class": cls,
        "diagnosis": diagnosis,
        "remediation": remediation,
        "detail": sanitize(detail, 200),
    }


def _classify(exc: Exception, endpoint: str) -> dict:
    name = type(exc).__name__
    detail = str(exc).strip()
    low = detail.lower()
    for predicate, cls, diagnosis, remediation in _RULES:
        if predicate(name, low, exc):
            return _verdict(cls, endpoint, diagnosis, remediation, detail)
    return _verdict(
        "unknown",
        endpoint,
        f"Unclassified connect failure ({name}).",
        "Inspect the detail; run 'iaiops doctor' and point at a local simulator to isolate.",
        detail,
    )


def diagnose_connection(target: Any) -> dict:
    """Attempt an OPC-UA connect and return a classified verdict (never raises).

    Classes: ``ok`` · ``certificate`` · ``auth`` · ``security_policy`` ·
    ``port_closed`` · ``dns`` · ``firewall_timeout`` · ``unreachable`` ·
    ``config`` · ``unknown``. Each carries a ``diagnosis`` and a ``remediation``.
    """
    endpoint = getattr(target, "endpoint_url", None) or getattr(target, "name", "?")
    try:
        client = _build_opcua_client(target)
    except OTConnectionError as exc:
        return _verdict(
            "config",
            endpoint,
            "Endpoint or client-library configuration problem (no connect attempted).",
            "Fix the endpoint config (endpoint_url) or install the connector "
            "('pip install iaiops[opcua]'), then retry.",
            str(exc),
        )
    try:
        client.connect()
    except Exception as exc:  # noqa: BLE001 — classify any connect failure
        return _classify(exc, endpoint)
    try:
        return _verdict(
            "ok",
            endpoint,
            "Connection succeeded — transport, security, and authentication all OK.",
            "No action needed.",
        )
    finally:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001 — disconnect must not mask the verdict
            pass
