"""OPC-UA connection self-diagnosis — classify a failed connect into a verdict."""

from __future__ import annotations

import os
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
        (RuntimeError("Bad_SecurityModeRejected"), "security_policy"),
        (RuntimeError("Bad_NoMatchingEndpoint"), "security_policy"),
        (RuntimeError("Bad_ConnectionRejected by SecureChannel"), "security_policy"),
        (ConnectionRefusedError("[Errno 61] Connection refused"), "port_closed"),
        (socket.gaierror("getaddrinfo failed"), "dns"),
        (TimeoutError("operation timed out"), "firewall_timeout"),
        (RuntimeError("Bad_Timeout"), "firewall_timeout"),
        (OSError("No route to host"), "unreachable"),
        (RuntimeError("The ServerUri is not a valid URI.(BadServerUriInvalid)"), "client_interop"),
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


def test_a_failed_connect_also_releases_the_client(monkeypatch):
    """The failure path must disconnect too — it is the path this tool lives on.

    ``asyncua.sync.Client`` runs a NON-daemon thread loop that only stops on
    ``disconnect()``. For a long time the OK path disconnected and the failure
    path returned straight from ``_classify``, so every failed diagnosis left a
    thread running: unbounded growth in an MCP server, and a CLI command that
    never returned to the prompt. See the subprocess test below — this one pins
    the contract, that one proves the real client honours it.
    """
    holder = _patch_build(monkeypatch, ConnectionRefusedError("[Errno 61] refused"))
    verdict = diag.diagnose_connection(TARGET)
    assert verdict["class"] == "port_closed"
    assert holder["client"].disconnected is True, "the failed connect leaked the client"


def test_config_error_before_connect(monkeypatch):
    def _build(_target):
        raise OTConnectionError("OPC-UA endpoint 'line1' has no endpoint_url.")

    monkeypatch.setattr(diag, "_build_opcua_client", _build)
    v = diag.diagnose_connection(TARGET)
    assert v["class"] == "config"
    assert v["reachable"] is False


def test_build_phase_non_ot_error_does_not_escape(monkeypatch):
    # a malformed URL / locked secret store raises a non-OTConnectionError in build;
    # it must be captured as a 'config' verdict, never propagated
    def _build(_target):
        raise ValueError("Invalid URL")

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


@pytest.mark.integration
@pytest.mark.parametrize(
    "target_expr, expected",
    [
        # The connect fails: the verdict path that returns straight from _classify.
        (
            "SimpleNamespace(name='x', protocol='opcua',"
            " endpoint_url='opc.tcp://127.0.0.1:1/', timeout_s=5,"
            " username='', password=lambda: '', client_cert='', client_key='',"
            " server_cert='', security_policy='', security_mode='')",
            "port_closed",
        ),
        # The BUILDER fails, after asyncua's constructor already started the thread
        # loop — a target missing a field stands in for the real cases (a locked
        # secret store behind password(), an unparseable security string).
        (
            "SimpleNamespace(name='x', protocol='opcua',"
            " endpoint_url='opc.tcp://127.0.0.1:1/', timeout_s=5)",
            "config",
        ),
    ],
)
def test_a_real_failed_diagnose_lets_the_process_exit(tmp_path, target_expr, expected):
    """The regression the mocked tests above cannot see: a hung interpreter.

    A fake client's `disconnect()` is a no-op, so those tests pass whether or not
    the real thread loop is stopped. `asyncua.sync.Client` starts a **non-daemon**
    ThreadLoop in its CONSTRUCTOR, so any path that abandons a client keeps the
    process alive forever — which is what an operator running `iaiops doctor` at
    a terminal actually saw, and what a long-lived MCP server would accumulate.

    Both abandoning paths are covered: the failed connect, and the builder
    raising after the constructor ran.
    """
    import subprocess
    import sys

    pytest.importorskip("asyncua", reason="asyncua not installed — install iaiops[opcua]")

    script = (
        "from types import SimpleNamespace\n"
        "from iaiops.connectors.opcua.diagnostics import diagnose_connection\n"
        f"t = {target_expr}\n"
        "print(diagnose_connection(t)['class'])\n"
    )
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,  # a leaked non-daemon thread makes this hang forever
        cwd=tmp_path,
        env={**os.environ, "IAIOPS_HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert expected in result.stdout, result.stdout
