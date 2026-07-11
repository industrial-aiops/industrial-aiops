"""InfluxDB historian sink — write OT telemetry to InfluxDB (v1 or v2).

A neutral, general-market target alongside the domestic historians (TDengine / IoTDB): iaiops binds
no store, so a site egresses to whatever it already runs. Uses the **InfluxDB line protocol over
HTTP** (no heavy client dependency — reuses ``requests``, the same pin as the MTConnect/IO-Link
extras), so it works against both InfluxDB **v2** (token + org + bucket) and **v1** (database).

This is **data egress to the operator's OWN historian**, not a control write — low-risk, still
governed/audited. The write surface is ``待核实`` against a live InfluxDB (isolated behind the
uniform ``write(points) -> int`` interface, so the push path is fully mock-testable).
"""

from __future__ import annotations

from datetime import UTC, datetime

from iaiops.core.sink.base import SinkError


class InfluxDBSink:
    """Uniform sink over the InfluxDB line-protocol write endpoint (v1 or v2). 待核实."""

    def __init__(self, url: str = "http://localhost:8086", token: str = "",
                 org: str = "", bucket: str = "", database: str = "iaiops",
                 timeout_s: float = 10.0) -> None:
        self._url = (url or "http://localhost:8086").rstrip("/")
        self._token = token or ""
        self._org = org or ""
        self._bucket = bucket or ""
        self._database = database or "iaiops"
        self._timeout = float(timeout_s or 10.0)

    def _endpoint(self) -> tuple[str, dict, dict]:
        """Resolve (write_url, params, headers) for v2 (token+bucket) or v1 (database)."""
        if self._token and self._bucket:  # v2
            return (
                f"{self._url}/api/v2/write",
                {"org": self._org, "bucket": self._bucket, "precision": "ns"},
                {"Authorization": f"Token {self._token}",
                 "Content-Type": "text/plain; charset=utf-8"},
            )
        return (  # v1
            f"{self._url}/write",
            {"db": self._database, "precision": "ns"},
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    def write(self, points: list[dict]) -> int:
        """POST normalized numeric points as line protocol; returns count written."""
        try:
            import requests
        except ImportError as exc:  # pragma: no cover — only without requests
            raise SinkError(
                "The 'requests' package is not installed. Install the InfluxDB sink: "
                "'pip install iaiops[influxdb]'."
            ) from exc
        lines = [self._line(p) for p in points if p.get("numeric")]
        lines = [ln for ln in lines if ln]
        if not lines:
            return 0
        url, params, headers = self._endpoint()
        try:
            resp = requests.post(
                url, params=params, headers=headers,
                data="\n".join(lines).encode("utf-8"), timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise SinkError(f"InfluxDB write to {url} failed: {exc}") from exc
        if resp.status_code >= 300:
            raise SinkError(
                f"InfluxDB write returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return len(lines)

    def close(self) -> None:  # stateless HTTP — nothing to close.
        return None

    @staticmethod
    def _line(p: dict) -> str:
        """One line-protocol record: ``metric[,tag=v...] value=<float> <ns>``."""
        metric = _escape_key(str(p.get("metric") or ""))
        if not metric:
            return ""
        tags = "".join(
            f",{_escape_key(str(k))}={_escape_key(str(v))}"
            for k, v in sorted((p.get("tags") or {}).items())
            if v not in (None, "")
        )
        ns = _ts_nanos(p.get("timestamp"))
        return f"{metric}{tags} value={float(p['value'])} {ns}"


def _escape_key(text: str) -> str:
    """Escape line-protocol special chars (comma, space, equals) in a measurement/tag token."""
    for a, b in (("\\", "\\\\"), (",", "\\,"), (" ", "\\ "), ("=", "\\=")):
        text = text.replace(a, b)
    return text[:180]


def _ts_nanos(timestamp) -> int:
    """Parse an ISO timestamp to epoch-nanoseconds (UTC); missing/unparseable falls back to now."""
    text = str(timestamp or "").strip()
    if text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp() * 1_000_000_000)
        except ValueError:
            pass
    return int(datetime.now(tz=UTC).timestamp() * 1_000_000_000)


__all__ = ["InfluxDBSink"]
