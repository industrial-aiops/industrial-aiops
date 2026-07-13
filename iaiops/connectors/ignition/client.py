"""Gateway HTTP/JSON client (READ-ONLY — no writes anywhere in this connector).

Same HTTP stack as the MTConnect / IO-Link / BAS connectors (``requests``,
lazily imported so the base package installs without it). The client is an
immutable per-call object: it holds the resolved base URL, the deployment
:class:`IgnitionDialect`, the API token/key and TLS/timeout knobs, and folds
every response through the dialect's pure normalizers before it reaches the
caller.

Every response is size-capped and JSON-checked with teaching errors. The
module-level ``_http_get`` is the ONLY network primitive (there is no PUT/POST —
this connector never writes); it is the test monkeypatch point, exercised by the
in-repo mock in ``tests/test_ignition_tools.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from iaiops.connectors.ignition.dialects import (
    IgnitionDialect,
    normalize_alarm,
    normalize_gateway,
    normalize_module,
    normalize_node,
    normalize_sample,
    normalize_tag,
)

# History responses can be large (many samples); cap at 4 MiB — well past any
# legitimate bounded page, still a hard ceiling against a hostile/broken gateway.
MAX_RESPONSE_BYTES = 4_194_304
_CHUNK_BYTES = 8192
MAX_NODES = 1000
MAX_TAGS = 500
MAX_SAMPLES = 5000


def _requests():  # -> module
    """Import ``requests`` lazily so the base package installs without it."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover — exercised only without requests
        from iaiops.core.runtime.session_factory import OTConnectionError

        raise OTConnectionError(
            "The 'requests' package is not installed. Install the Gateway "
            "read-layer connector: 'pip install iaiops[ignition]'."
        ) from exc
    return requests


def _read_capped(resp: Any, url: str) -> str:
    """Stream the response body, refusing anything over MAX_RESPONSE_BYTES."""
    body = b""
    for chunk in resp.iter_content(_CHUNK_BYTES):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"Gateway at {url} returned more than {MAX_RESPONSE_BYTES} bytes; "
                f"refused (response size cap)."
            )
    return body.decode("utf-8", errors="replace")


def _headers(token: str, accept: str) -> dict[str, str]:
    """Build request headers: JSON accept + optional bearer/API-key authorization."""
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_get(url: str, headers: dict[str, str], timeout: float, verify: bool) -> str:
    """GET ``url`` → capped text body. The sole network primitive; patched in tests."""
    resp = _requests().get(url, headers=headers, timeout=timeout, verify=verify, stream=True)
    resp.raise_for_status()
    return _read_capped(resp, url)


def _parse_json(body: str, url: str) -> Any:
    """Parse a gateway response as JSON, teaching on garbage."""
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Gateway at {url} returned unparseable JSON: {exc}. Check the base URL "
            f"points at the Gateway's HTTP/web-API surface and that JSON responses "
            f"are enabled (Accept: application/json)."
        ) from exc


def _q(value: str) -> str:
    """Percent-encode a path/query fragment (safe='' — encode slashes too)."""
    return quote(str(value), safe="")


@dataclass(frozen=True)
class IgnitionClient:
    """Immutable per-call READ-ONLY client for one Gateway HTTP web API."""

    base_url: str
    dialect: IgnitionDialect
    token: str = field(default="", repr=False)
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
    def gateway_status(self) -> dict[str, Any]:
        """Gateway/module health envelope, normalized to {gateway, modules}."""
        payload = self._get(self.dialect.status_path)
        gateway = normalize_gateway(payload, self.dialect)
        modules = [normalize_module(m, self.dialect) for m in self.dialect.modules(payload)]
        return {"gateway": gateway, "modules": modules}

    def browse(self, provider: str, path: str = "") -> list[dict[str, Any]]:
        """Browse the tag tree under a provider/path, normalized (bounded)."""
        req = self.dialect.browse_path.format(provider=_q(provider), path=_q(path))
        payload = self._get(req)
        nodes = self.dialect.nodes(payload)[:MAX_NODES]
        return [normalize_node(n, self.dialect) for n in nodes]

    def read(self, provider: str, tag_paths: list[str]) -> list[dict[str, Any]]:
        """Read current value(s) for one or more tag paths, normalized (bounded)."""
        joined = ",".join(_q(p) for p in list(tag_paths)[:MAX_TAGS])
        # joined is already component-encoded; keep it out of a second encode pass.
        req = self.dialect.read_path.replace("{provider}", _q(provider)).replace("{path}", joined)
        payload = self._get(req)
        tags = self.dialect.tags(payload)[:MAX_TAGS]
        return [normalize_tag(t, self.dialect) for t in tags]

    def alarms(self) -> list[dict[str, Any]]:
        """List active/acknowledged alarms, normalized (bounded)."""
        payload = self._get(self.dialect.alarms_path)
        items = self.dialect.alarms(payload)[:MAX_NODES]
        return [normalize_alarm(a, self.dialect) for a in items]

    def history(
        self, provider: str, tag_path: str, start: str, end: str, count: int = 100
    ) -> list[dict[str, Any]]:
        """Read a tag's historian samples over a window, normalized (bounded)."""
        cap = max(1, min(int(count), MAX_SAMPLES))
        req = (
            self.dialect.history_path.replace("{provider}", _q(provider))
            .replace("{path}", _q(tag_path))
            .replace("{start}", _q(start))
            .replace("{end}", _q(end))
            .replace("{count}", str(cap))
        )
        payload = self._get(req)
        items = self.dialect.samples(payload)[:cap]
        return [normalize_sample(s, self.dialect) for s in items]


__all__ = [
    "MAX_NODES",
    "MAX_RESPONSE_BYTES",
    "MAX_SAMPLES",
    "MAX_TAGS",
    "IgnitionClient",
]
