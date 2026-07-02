"""IO-Link master HTTP/JSON client (IOLINK-JSON, read-only).

Speaks the IO-Link consortium "IO-Link Master — JSON Integration" surface in the
two shapes deployed masters actually expose:

* ``iotcore`` (default) — the ifm IoT-Core envelope: every read is an HTTP POST
  of ``{"code": "request", "cid": <n>, "adr": "<path>", ["data": {...}]}`` to the
  master root ``/``; the reply is ``{"cid": n, "code": 200, "data": {"value": ...}}``.
  Used by ifm AL13xx/AL19xx-style masters.
* ``rest`` — plain-REST GET of the same ``adr`` path directly as a URL
  (Balluff/Turck-style JSON masters). Reply envelopes vary by vendor, so the
  parser accepts the IoT-Core envelope, a bare ``{"value": ...}``, or a raw JSON
  scalar. Vendor-specific path prefixes remain 待核实.

Same HTTP stack as the MTConnect connector (``requests``, lazily imported); the
module-level ``_http_get`` / ``_http_post`` are the test monkeypatch points.
Every response is size-capped and JSON-schema-checked with teaching errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

FLAVOR_IOTCORE = "iotcore"
FLAVOR_REST = "rest"
FLAVORS = (FLAVOR_IOTCORE, FLAVOR_REST)

# Bound every master response: identity strings + pdin hex + ISDU payloads are
# tiny (bytes to a few KB); anything past this is a misbehaving/hostile server.
MAX_RESPONSE_BYTES = 262_144
_CHUNK_BYTES = 8192
_IOTCORE_OK = 200


def _requests():  # -> module
    """Import ``requests`` lazily so the base package installs without it."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover — exercised only without requests
        from iaiops.core.runtime.session_factory import OTConnectionError

        raise OTConnectionError(
            "The 'requests' package is not installed. Install the IO-Link "
            "connector: 'pip install iaiops[iolink]'."
        ) from exc
    return requests


def _read_capped(resp: Any, url: str) -> str:
    """Stream the response body, refusing anything over MAX_RESPONSE_BYTES."""
    body = b""
    for chunk in resp.iter_content(_CHUNK_BYTES):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"IO-Link master at {url} returned more than "
                f"{MAX_RESPONSE_BYTES} bytes; refused (response size cap)."
            )
    return body.decode("utf-8", errors="replace")


def _http_get(url: str, timeout: float) -> str:
    """GET ``url`` → capped text body. Monkeypatched in tests."""
    resp = _requests().get(url, timeout=timeout, stream=True)
    resp.raise_for_status()
    return _read_capped(resp, url)


def _http_post(url: str, payload: dict, timeout: float) -> str:
    """POST a JSON envelope to ``url`` → capped text body. Monkeypatched in tests."""
    resp = _requests().post(url, json=payload, timeout=timeout, stream=True)
    resp.raise_for_status()
    return _read_capped(resp, url)


def _parse_json(body: str, url: str) -> Any:
    """Parse a master response as JSON, teaching on garbage."""
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"IO-Link master at {url} returned unparseable JSON: {exc}. "
            f"Check the base URL points at a JSON-capable IO-Link master "
            f"(flavor iotcore|rest)."
        ) from exc


def _extract_value(payload: Any, adr: str) -> Any:
    """Schema-check a master reply and dig out the value.

    Accepts the IoT-Core envelope (``{"cid", "code", "data": {"value": ...}}``),
    a bare ``{"value": ...}`` / ``{"data": ...}`` object, or a raw JSON scalar —
    the plain-REST shape varies by vendor (待核实).
    """
    if isinstance(payload, dict) and "code" in payload:
        code = payload.get("code")
        if code != _IOTCORE_OK:
            raise ValueError(
                f"IO-Link master rejected '{adr}' with code {code!r} "
                f"(expected {_IOTCORE_OK}). The port may be empty, the datapoint "
                f"unsupported on this master, or the adr path wrong."
            )
        payload = payload.get("data")
    if isinstance(payload, dict):
        if "value" in payload:
            return payload["value"]
        if "data" in payload:  # some plain-REST masters nest once more; 待核实
            inner = payload["data"]
            return inner.get("value", inner) if isinstance(inner, dict) else inner
        return payload
    return payload


@dataclass(frozen=True)
class IoLinkClient:
    """Immutable per-call client for one IO-Link master (read-only)."""

    base_url: str
    flavor: str = FLAVOR_IOTCORE
    timeout_s: float = 10.0

    def request(self, adr: str, data: dict | None = None) -> Any:
        """Read one datapoint ``adr`` (e.g. ``/iolinkmaster/port[1]/iolinkdevice/pdin/getdata``).

        ``data`` carries service arguments (ISDU index/subindex). Returns the
        extracted value (string/number/object per datapoint).
        """
        adr = "/" + adr.strip("/")
        if self.flavor == FLAVOR_REST:
            url = f"{self.base_url}{adr}"
            if data:
                # Plain-REST argument passing is not standardized across vendors
                # (待核实): pass service args as a query string, the common shape.
                query = "&".join(f"{k}={v}" for k, v in sorted(data.items()))
                url = f"{url}?{query}"
            body = _http_get(url, self.timeout_s)
            return _extract_value(_parse_json(body, url), adr)
        url = f"{self.base_url}/"
        envelope: dict[str, Any] = {"code": "request", "cid": 1, "adr": adr}
        if data:
            envelope["data"] = dict(data)
        body = _http_post(url, envelope, self.timeout_s)
        return _extract_value(_parse_json(body, url), adr)


__all__ = [
    "FLAVOR_IOTCORE",
    "FLAVOR_REST",
    "FLAVORS",
    "IoLinkClient",
    "MAX_RESPONSE_BYTES",
]
