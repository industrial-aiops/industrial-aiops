"""OPC-UA connection self-diagnosis — classify a failed connect into a verdict."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from iaiops.connectors.opcua import diagnostics as diag
from iaiops.core.runtime.connection import OTConnectionError

TARGET = SimpleNamespace(name="line1", endpoint_url="opc.tcp://plc:4840", protocol="opcua")


class _FakeClient:
    def __init__(self, on_connect):
        self._on_connect = on_connect
        self.disconnected = False

    def connect(self):
        if self._on_connect is not None:
            raise self._on_connect

    def disconnect(self):
        self.disconnected = True


def _patch_build(monkeypatch, on_connect):
    holder = {}

    def _build(_target):
        holder["client"] = _FakeClient(on_connect)
        return holder["client"]

    monkeypatch.setattr(diag, "_build_opcua_client", _build)
    return holder


def test_ok_connects_and_disconnects(monkeypatch):
    holder = _patch_build(monkeypatch, None)
    v = diag.diagnose_connection(TARGET)
    assert v["class"] == "ok"
    assert v["reachable"] is True
    assert holder["client"].disconnected is True  # always disconnects


@pytest.mark.parametrize(
    "exc, expected",
    [
        (RuntimeError("Bad_SecurityChecksFailed: cert not trusted"), "certificate"),
        (RuntimeError("Bad_CertificateUntrusted"), "certificate"),
        (RuntimeError("Bad_UserAccessDenied"), "auth"),
        (RuntimeError("The IdentityToken is not valid"), "auth"),
        (RuntimeError("Bad_SecurityPolicyRejected"), "security_policy"),
        (RuntimeError("Bad_ConnectionRejected by SecureChannel"), "security_policy"),
        (ConnectionRefusedError("[Errno 61] Connection refused"), "port_closed"),
        (socket.gaierror("getaddrinfo failed"), "dns"),
        (TimeoutError("operation timed out"), "firewall_timeout"),
        (OSError("No route to host"), "unreachable"),
        (ValueError("something unexpected"), "unknown"),
    ],
)
def test_classifies_connect_failures(monkeypatch, exc, expected):
    _patch_build(monkeypatch, exc)
    v = diag.diagnose_connection(TARGET)
    assert v["class"] == expected
    assert v["reachable"] is False
    assert v["remediation"]  # every verdict carries a concrete next step
    assert v["diagnosis"]


def test_config_error_before_connect(monkeypatch):
    def _build(_target):
        raise OTConnectionError("OPC-UA endpoint 'line1' has no endpoint_url.")

    monkeypatch.setattr(diag, "_build_opcua_client", _build)
    v = diag.diagnose_connection(TARGET)
    assert v["class"] == "config"
    assert v["reachable"] is False


def test_never_raises_and_sanitizes_detail(monkeypatch):
    # a giant noisy error must be captured + truncated, not propagated
    _patch_build(monkeypatch, RuntimeError("x" * 1000))
    v = diag.diagnose_connection(TARGET)
    assert v["class"] == "unknown"
    assert len(v["detail"]) <= 200
