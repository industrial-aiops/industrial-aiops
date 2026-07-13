"""Shared historian-sink helpers — point normalization + the sink factory.

A "sink" writes already-collected OT telemetry to a national time-series database
(TDengine / IoTDB) — the 信创 requirement that monitoring data lands in a
domestic, controllable historian rather than InfluxDB or a self-built store. This
is **data egress to the operator's OWN historian**, not a control-system write, so
it is low-risk (still governed/audited).

The adapters (one per TSDB) live in sibling modules and lazy-import their client
library, so the base package imports without any of them. Their write surface is
``待核实`` (unverified against a live cluster) — isolated behind a uniform
``write(points) -> int`` interface so the push path is fully mock-testable.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, s

MAX_POINTS = 100_000  # bounded batch (defensive)
SUPPORTED_SINKS = ("tdengine", "iotdb", "sqlite", "influxdb")
# Sinks whose value column keeps non-numeric values (as text) instead of skipping.
TEXT_CAPABLE_SINKS = ("sqlite",)


class SinkError(Exception):
    """A historian-sink operation failed; carries a teaching message."""


def normalize_points(points: list[Any]) -> list[dict]:
    """Coerce raw collected points to uniform ``{metric, value, timestamp, tags}``.

    Accepts the shapes the collectors/connectors emit — e.g. ``{ref, value,
    timestamp}``, ``{io_address, value, recorded_at}``, ``{object_type, instance,
    present_value}`` — and maps each to a metric name + numeric/string value +
    optional timestamp + tag dict. Non-numeric values are kept as strings.
    """
    out: list[dict] = []
    for item in list(points or [])[:MAX_POINTS]:
        if not isinstance(item, dict):
            continue
        metric = _metric_name(item)
        if not metric:
            continue
        raw = item.get("value")
        if raw is None:  # explicit fallback so a present value=None doesn't mask present_value
            raw = item.get("present_value")
        value = num(raw)
        out.append(
            {
                "metric": s(metric, 128),
                "value": value if value is not None else s(raw, 128),
                "numeric": value is not None,
                "timestamp": s(item.get("timestamp", item.get("recorded_at", "")), 40),
                "tags": _tags(item),
            }
        )
    return out


def _metric_name(item: dict) -> str:
    """Derive a stable metric name from whatever identifier the point carries."""
    for key in ("metric", "ref", "reference"):
        if item.get(key):
            return str(item[key])
    if item.get("object_type") is not None and item.get("instance") is not None:
        return f"{item['object_type']}.{item['instance']}"
    if item.get("io_address") is not None:
        return f"ioa.{item['io_address']}"
    if item.get("index") is not None and item.get("type"):
        return f"{item['type']}.{item['index']}"
    return ""


def _tags(item: dict) -> dict:
    """Carry through a small, bounded set of identifying tags."""
    tags: dict[str, str] = {}
    for key in ("quality", "type", "object_type", "common_address", "group", "unit"):
        if item.get(key) not in (None, ""):
            tags[key] = s(item[key], 48)
    return tags


def get_sink(kind: str, **opts: Any) -> Any:
    """Return a historian-sink adapter for ``kind`` (tdengine / iotdb / sqlite)."""
    k = (kind or "").strip().lower()
    if k == "sqlite":
        from iaiops.core.sink.sqlite_local import SQLiteLocalSink

        return SQLiteLocalSink(**opts)
    if k == "tdengine":
        from iaiops.core.sink.tdengine import TDengineSink

        return TDengineSink(**opts)
    if k == "iotdb":
        from iaiops.core.sink.iotdb import IoTDBSink

        return IoTDBSink(**opts)
    if k == "influxdb":
        from iaiops.core.sink.influxdb import InfluxDBSink

        return InfluxDBSink(**opts)
    raise SinkError(f"Unknown historian sink '{kind}'. Supported: {', '.join(SUPPORTED_SINKS)}.")


__all__ = [
    "SinkError",
    "normalize_points",
    "get_sink",
    "SUPPORTED_SINKS",
    "TEXT_CAPABLE_SINKS",
    "MAX_POINTS",
]
