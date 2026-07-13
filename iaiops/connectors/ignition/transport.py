"""Gateway read-layer transport: client build + error translation + session.

The Gateway HTTP read layer is edition-scoped (factory edition) and speaks a
vendor SCADA/MES platform's web API, not a neutral field-bus wire protocol — so
it is deliberately NOT registered in ``config.SUPPORTED_PROTOCOLS`` /
``profiles.PROTOCOL_MODULES``. Instead the connector carries its own tiny,
immutable :class:`IgnitionTarget` (built from tool arguments, not the YAML
endpoint config) and assembles its own stateless-HTTP ``ignition_session`` right
here via the shared :func:`make_session` lifecycle — the same factory HART /
IO-Link / BAS use, reused without leaking a vendor name into core.

The "connection" is stateless HTTP: build resolves the base URL + dialect; there
is no connect/close. Failures translate to a teaching ``OTConnectionError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from iaiops.connectors.ignition.client import IgnitionClient
from iaiops.connectors.ignition.dialects import UnknownFlavorError, get_dialect
from iaiops.core.runtime.config import DEFAULT_TIMEOUT_S
from iaiops.core.runtime.session_factory import OTConnectionError, make_session
from iaiops.core.runtime.url_guard import UrlEgressError, validate_base_url

# The connector-local protocol tag the local session guards on. It is NOT a
# public wire protocol (never added to SUPPORTED_PROTOCOLS) — only this session
# accepts it, so the shared make_session guard still works unchanged.
_IGNITION_PROTOCOL = "ignition"


@dataclass(frozen=True)
class IgnitionTarget:
    """Immutable per-call Gateway target (from tool args, not YAML config).

    Mirrors the shape :func:`make_session` expects (``name`` + ``protocol``) so
    the shared lifecycle guards/translates exactly as for a real endpoint,
    without a YAML ``TargetConfig`` (which would require registering this as a
    core protocol — this layer is edition-scoped, so it does not).
    """

    name: str
    base_url: str
    flavor: str
    token: str = field(default="", repr=False)  # API-key/token secret — keep out of repr
    timeout_s: float = DEFAULT_TIMEOUT_S
    verify_tls: bool = True
    protocol: str = _IGNITION_PROTOCOL


def _build_ignition_client(target: IgnitionTarget) -> IgnitionClient:
    """Construct the stateless HTTP client for ``target``. Module-level patch point."""
    base = (target.base_url or "").rstrip("/")
    if not base:
        raise OTConnectionError(
            f"Gateway '{target.name}' has no base_url. Pass the Gateway HTTP base, "
            f"e.g. 'https://<gateway-host>:8043'.",
            endpoint=target.name,
            protocol=_IGNITION_PROTOCOL,
        )
    try:
        # Egress guard BEFORE any network I/O: http(s)-only, no URL-embedded
        # credentials, and a stored API token only rides to an internal host
        # or one the operator allowlisted (IAIOPS_TOKEN_EGRESS_HOSTS) — this
        # blocks stored-token exfiltration via a caller-supplied base_url.
        validate_base_url(base, connector="Gateway", token_attached=bool(target.token))
    except UrlEgressError as exc:
        raise OTConnectionError(
            str(exc), endpoint=target.name, protocol=_IGNITION_PROTOCOL
        ) from exc
    try:
        dialect = get_dialect(target.flavor)
    except UnknownFlavorError as exc:
        raise OTConnectionError(
            str(exc), endpoint=target.name, protocol=_IGNITION_PROTOCOL
        ) from exc
    return IgnitionClient(
        base_url=base,
        dialect=dialect,
        token=target.token,
        timeout_s=target.timeout_s,
        verify_tls=target.verify_tls,
    )


def _translate_ignition(exc: Exception, target: IgnitionTarget) -> OTConnectionError:
    """Map an HTTP/parse failure to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    return OTConnectionError(
        f"Gateway read on '{target.name}' ({target.base_url}) failed: {detail}. "
        f"Check the base URL, that the Gateway's HTTP/web-API is reachable, and "
        f"that the API token/secret is valid.",
        endpoint=target.base_url or target.name,
        protocol=_IGNITION_PROTOCOL,
    )


# Stateless HTTP (like IO-Link/MTConnect/BAS): build resolves base URL + dialect;
# no connect/close. The session still guards the protocol and translates failures.
ignition_session = make_session(
    protocol=_IGNITION_PROTOCOL,
    build=lambda target: _build_ignition_client(target),
    translate=_translate_ignition,
    name="ignition_session",
)


__all__ = [
    "IgnitionTarget",
    "_build_ignition_client",
    "_translate_ignition",
    "ignition_session",
]
