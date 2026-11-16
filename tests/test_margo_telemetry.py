"""The edge OTLP path exports only local health and refuses public destinations."""

from __future__ import annotations

import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from mcp_server.telemetry import _audit_snapshot, _collector_endpoint, start_health_metrics


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://8.8.8.8:4318/v1/metrics",
        "http://169.254.169.254:4318/v1/metrics",
        "https://collector.example.com:4318/v1/metrics",
        "http://user:pass@127.0.0.1:4318/v1/metrics",
        "http://127.0.0.1:4318/v1/metrics?token=secret",
    ],
)
def test_public_or_sensitive_collector_is_refused(endpoint: str) -> None:
    with pytest.raises(ValueError):
        _collector_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    ["http://127.0.0.1:4318/v1/metrics", "http://192.168.1.21:4318/v1/metrics"],
)
def test_local_collector_is_allowed(endpoint: str) -> None:
    assert _collector_endpoint(endpoint) == endpoint


def test_missing_audit_is_unavailable_not_zero(tmp_path: Path) -> None:
    assert _audit_snapshot(tmp_path / "missing.db") == (0, 0, False)


def test_audit_counts_only_status(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE audit_log (status TEXT, secret TEXT)")
        conn.executemany(
            "INSERT INTO audit_log VALUES (?, ?)", [("ok", "private-a"), ("error", "private-b")]
        )
    assert _audit_snapshot(path) == (2, 1, True)


def test_export_stays_off_by_default_and_under_no_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_METRICS_EXPORTER", raising=False)
    assert start_health_metrics() is None
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "otlp")
    monkeypatch.setenv("IAIOPS_NO_EGRESS", "1")
    assert start_health_metrics() is None


def test_local_otlp_receiver_gets_health_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
        ExportMetricsServiceRequest,
    )

    state = tmp_path / "state"
    state.mkdir()
    with sqlite3.connect(state / "audit.db") as conn:
        conn.execute("CREATE TABLE audit_log (status TEXT, secret TEXT)")
        conn.execute("INSERT INTO audit_log VALUES ('ok', 'never-export-this-secret')")

    received: list[bytes] = []
    received_headers: list[dict[str, str]] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            assert self.path == "/v1/metrics"
            received_headers.append(dict(self.headers.items()))
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    receiver = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("IAIOPS_HOME", str(state))
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "private.key=never-export-this-secret")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "X-Api-Key=never-export-this-secret")
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.delenv("IAIOPS_NO_EGRESS", raising=False)
        monkeypatch.setenv("OTEL_METRICS_EXPORTER", "otlp")
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            f"http://127.0.0.1:{receiver.server_port}/v1/metrics",
        )
        provider = start_health_metrics()
        assert provider is not None
        try:
            assert provider.force_flush(timeout_millis=5000)
        finally:
            provider.shutdown()
        assert received
        request = ExportMetricsServiceRequest.FromString(received[0])
        names = {
            metric.name
            for resource in request.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }
        assert names == {
            "iaiops.process.uptime",
            "iaiops.audit.events",
            "iaiops.audit.errors",
            "iaiops.audit.available",
        }
        values = {
            metric.name: metric.gauge.data_points[0].as_int
            for resource in request.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
            if metric.name.startswith("iaiops.audit.")
        }
        assert values == {
            "iaiops.audit.events": 1,
            "iaiops.audit.errors": 0,
            "iaiops.audit.available": 1,
        }
        assert b"never-export-this-secret" not in received[0]
        assert "X-Api-Key" not in received_headers[0]
    finally:
        receiver.shutdown()
        receiver.server_close()
        thread.join(timeout=5)
