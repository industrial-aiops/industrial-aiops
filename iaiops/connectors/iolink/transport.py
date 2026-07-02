"""IO-Link transport: HTTP/JSON client build + error translation (B1 pattern).

The assembled ``iolink_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests monkeypatch
``connection._build_iolink_client``. The "connection" is stateless HTTP — build
just resolves the base URL + flavor; there is no connect/close.
"""

from __future__ import annotations

from iaiops.connectors.iolink.client import FLAVOR_IOTCORE, FLAVORS, IoLinkClient
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError

DEFAULT_IOLINK_HTTP_PORT = 80


def _iolink_base_url(target: TargetConfig) -> str:
    """Resolve the IO-Link master base URL from the endpoint config."""
    base = (target.agent_url or "").rstrip("/")
    if not base and target.host:
        port = target.port or DEFAULT_IOLINK_HTTP_PORT
        base = f"http://{target.host}:{port}"
    if not base:
        raise OTConnectionError(
            f"IO-Link endpoint '{target.name}' has no agent_url. Add "
            f"'agent_url: http://<master-ip>' (or host/port) to its config entry.",
            endpoint=target.name,
            protocol="iolink",
        )
    return base


def _build_iolink_client(target: TargetConfig) -> IoLinkClient:
    """Construct the stateless HTTP client for ``target``. Module-level patch point."""
    flavor = (target.flavor or FLAVOR_IOTCORE).strip().lower()
    if flavor not in FLAVORS:
        raise OTConnectionError(
            f"IO-Link endpoint '{target.name}' has unknown flavor '{target.flavor}'. "
            f"Use 'flavor: iotcore' (ifm IoT-Core POST envelope, default) or "
            f"'flavor: rest' (plain-REST GET).",
            endpoint=target.name,
            protocol="iolink",
        )
    return IoLinkClient(
        base_url=_iolink_base_url(target),
        flavor=flavor,
        timeout_s=target.timeout_s,
    )


def _translate_iolink(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map an HTTP/parse failure to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    where = target.agent_url or f"{target.host}:{target.port or DEFAULT_IOLINK_HTTP_PORT}"
    return OTConnectionError(
        f"IO-Link operation on '{target.name}' ({where}) failed: {detail}. Check "
        f"the master base URL, that its JSON/REST interface is enabled, and the "
        f"flavor (iotcore for ifm IoT-Core masters, rest for plain-REST masters).",
        endpoint=where,
        protocol="iolink",
    )


__all__ = ["_build_iolink_client", "_iolink_base_url", "_translate_iolink"]
