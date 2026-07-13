"""BAS controller HTTP/JSON client (read-first; ONE guarded command).

Same HTTP stack as the MTConnect / IO-Link connectors (``requests``, lazily
imported so the base package installs without it). The client is an immutable
per-call object: it holds the resolved base URL, the vendor :class:`BasDialect`,
the bearer token and TLS/timeout knobs, and folds every vendor-shaped response
through the dialect's pure normalizers before it reaches the caller.

Every response is size-capped and JSON-schema-checked with teaching errors. The
module-level ``_http_get`` / ``_http_put`` are the test monkeypatch points; the
in-repo mock in ``tests/test_bas_tools.py`` exercises the full request path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from iaiops.connectors.bas.dialects import (
    BasDialect,
    normalize_alarm,
    normalize_point,
    normalize_sample,
)

# Trend responses can be large (many samples); cap at 4 MiB — well past any
# legitimate bounded page, still a hard ceiling against a hostile/broken server.
MAX_RESPONSE_BYTES = 4_194_304
_CHUNK_BYTES = 8192
MAX_POINTS = 500
MAX_SAMPLES = 5000


def _requests():  # -> module
    """Import ``requests`` lazily so the base package installs without it."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover — exercised only without requests
        from iaiops.core.runtime.session_factory import OTConnectionError

        raise OTConnectionError(
            "The 'requests' package is not installed. Install the BAS "
            "controller connector: 'pip install iaiops[bas]'."
        ) from exc
    return requests


def _read_capped(resp: Any, url: str) -> str:
    """Stream the response body, refusing anything over MAX_RESPONSE_BYTES."""
    body = b""
    for chunk in resp.iter_content(_CHUNK_BYTES):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"BAS controller at {url} returned more than "
                f"{MAX_RESPONSE_BYTES} bytes; refused (response size cap)."
            )
    return body.decode("utf-8", errors="replace")


def _headers(token: str, accept: str) -> dict[str, str]:
    """Build request headers: JSON accept + optional bearer authorization."""
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_get(url: str, headers: dict[str, str], timeout: float, verify: bool) -> str:
    """GET ``url`` → capped text body. Monkeypatched in tests."""
    resp = _requests().get(url, headers=headers, timeout=timeout, verify=verify, stream=True)
    resp.raise_for_status()
    return _read_capped(resp, url)


def _http_put(
    url: str, payload: dict, headers: dict[str, str], timeout: float, verify: bool
) -> int:
    """PUT a JSON body to ``url`` → HTTP status code. Monkeypatched in tests."""
    resp = _requests().put(url, json=payload, headers=headers, timeout=timeout, verify=verify)
    resp.raise_for_status()
    return int(resp.status_code)


def _parse_json(body: str, url: str) -> Any:
    """Parse a controller response as JSON, teaching on garbage."""
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"BAS controller at {url} returned unparseable JSON: {exc}. Check the "
            f"base URL points at the controller's REST/oBIX-JSON surface and that "
            f"JSON responses are enabled (Accept: application/json)."
        ) from exc


@dataclass(frozen=True)
class BasClient:
    """Immutable per-call client for one BAS supervisory controller."""

    base_url: str
    dialect: BasDialect
    token: str = ""
    timeout_s: float = 10.0
    verify_tls: bool = True

    # ── low-level ────────────────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str) -> Any:
        url = self._url(path)
        body = _http_get(
            url, _headers(self.token, self.dialect.accept), self.timeout_s, self.verify_tls
        )
        return _parse_json(body, url)

    # ── read surface (normalized via the dialect) ────────────────────────────
    def list_points(self) -> list[dict[str, Any]]:
        """List controller points, normalized to {id, name, value, unit, status}."""
        payload = self._get(self.dialect.points_path)
        items = self.dialect.items(payload)[:MAX_POINTS]
        return [normalize_point(o, self.dialect) for o in items]

    def read_point(self, point_id: str) -> dict[str, Any]:
        """Read one point's present value, normalized."""
        path = self.dialect.point_path.format(id=quote(str(point_id), safe=""))
        return normalize_point(self._get(path), self.dialect)

    def read_points(self, point_ids: list[str]) -> list[dict[str, Any]]:
        """Read many points' present values (bounded)."""
        return [self.read_point(pid) for pid in list(point_ids)[:MAX_POINTS]]

    def list_alarms(self) -> list[dict[str, Any]]:
        """List active alarms/events, normalized."""
        payload = self._get(self.dialect.alarms_path)
        items = self.dialect.items(payload)[:MAX_POINTS]
        return [normalize_alarm(o, self.dialect) for o in items]

    def read_trend(self, point_id: str, count: int = 100) -> list[dict[str, Any]]:
        """Read a point's historical trend samples, normalized (bounded)."""
        path = self.dialect.trend_path.format(id=quote(str(point_id), safe=""))
        payload = self._get(path)
        cap = max(1, min(int(count), MAX_SAMPLES))
        items = self.dialect.items(payload)[:cap]
        return [normalize_sample(o, self.dialect) for o in items]

    # ── ONE guarded write ────────────────────────────────────────────────────
    def command(self, point_id: str, value: Any) -> bool:
        """Command (write) a point's value. Returns True on a 2xx acknowledgement."""
        path = self.dialect.command_path.format(id=quote(str(point_id), safe=""))
        url = self._url(path)
        status = _http_put(
            url,
            {self.dialect.write_value_field: value},
            _headers(self.token, self.dialect.accept),
            self.timeout_s,
            self.verify_tls,
        )
        return 200 <= status < 300


__all__ = [
    "MAX_POINTS",
    "MAX_RESPONSE_BYTES",
    "MAX_SAMPLES",
    "BasClient",
]
