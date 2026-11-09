"""Opt-in, local-only OTLP health metrics for the Margo edge process.

This module never reads OT sample data or audit row contents. It is deliberately
separate from the Prometheus tag-value bridge, whose labels include OT names.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

from iaiops.core.governance.paths import ops_path
from mcp_server.noegress import NO_EGRESS_ENV, no_egress_enabled

_log = logging.getLogger(__name__)
_STARTED = time.monotonic()
_DEFAULT_ENDPOINT = "http://127.0.0.1:4318/v1/metrics"
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)


def _collector_endpoint(raw: str) -> str:
    """Allow only an explicit loopback/private IP collector, never public DNS."""
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1/metrics"
    ):
        raise ValueError("OTLP metrics endpoint must be HTTP(S) /v1/metrics without credentials")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("OTLP metrics collector must use a loopback/private IP literal") from exc
    if not any(address in network for network in _LOCAL_NETWORKS) or not port:
        raise ValueError("OTLP metrics collector must use a loopback/private IP and explicit port")
    return raw


def _audit_snapshot(path: Path | None = None) -> tuple[int, int, bool]:
    """Return (events, errors, available); missing/broken audit is not healthy zero."""
    db = path or ops_path("audit.db")
    if not db.is_file():
        return 0, 0, False
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1) as conn:
            events = int(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
            errors = int(
                conn.execute("SELECT COUNT(*) FROM audit_log WHERE status != 'ok'").fetchone()[0]
            )
        return events, errors, True
    except (OSError, sqlite3.Error):
        _log.warning("Audit metrics unavailable", exc_info=True)
        return 0, 0, False


def start_health_metrics() -> object | None:
    """Start OTLP/HTTP export only after explicit opt-in and egress check.

    Returns the MeterProvider so the caller may retain it for process lifetime.
    Invalid configuration disables metrics and leaves the governed MCP server up.
    """
    exporter = os.environ.get("OTEL_METRICS_EXPORTER", "none").strip().lower()
    if exporter == "none":
        return None
    if exporter != "otlp":
        _log.warning("Unsupported OTEL_METRICS_EXPORTER; health metrics disabled")
        return None
    if no_egress_enabled(os.environ.get(NO_EGRESS_ENV)):
        _log.warning("IAIOPS_NO_EGRESS is on; OTLP health metrics disabled")
        return None
    if os.environ.get("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", "http/protobuf") != "http/protobuf":
        _log.warning("Only OTLP http/protobuf metrics are supported; health metrics disabled")
        return None
    try:
        endpoint = _collector_endpoint(
            os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", _DEFAULT_ENDPOINT)
        )
    except ValueError as exc:
        _log.warning("OTLP health metrics disabled: %s", exc)
        return None

    try:
        import requests
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.metrics import Observation
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        _log.warning("OTLP health metrics disabled: install iaiops[telemetry]")
        return None

    session = requests.Session()
    session.trust_env = False  # Never route a local collector through HTTP_PROXY.
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, headers={}, timeout=5, session=session),
        export_interval_millis=30000,
    )
    provider = MeterProvider(
        resource=Resource({"service.name": "iaiops-margo"}), metric_readers=[reader]
    )
    meter = provider.get_meter("iaiops.edge.health")

    def uptime(_options):
        yield Observation(max(0, time.monotonic() - _STARTED))

    def audit_events(_options):
        events, _errors, available = _audit_snapshot()
        if available:
            yield Observation(events)

    def audit_errors(_options):
        _events, errors, available = _audit_snapshot()
        if available:
            yield Observation(errors)

    def audit_available(_options):
        yield Observation(int(_audit_snapshot()[2]))

    meter.create_observable_gauge("iaiops.process.uptime", callbacks=[uptime], unit="s")
    meter.create_observable_gauge("iaiops.audit.events", callbacks=[audit_events], unit="1")
    meter.create_observable_gauge("iaiops.audit.errors", callbacks=[audit_errors], unit="1")
    meter.create_observable_gauge("iaiops.audit.available", callbacks=[audit_available], unit="1")
    metrics.set_meter_provider(provider)
    _log.info("OTLP health metrics enabled for local/private collector")
    return provider


__all__ = ["start_health_metrics"]
