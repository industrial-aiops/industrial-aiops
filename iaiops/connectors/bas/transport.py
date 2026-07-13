"""BAS transport: client build + error translation + session assembly.

The BAS controller layer is edition-scoped (building edition) and speaks a
vendor supervisory REST API, not a neutral field-bus wire protocol — so it is
deliberately NOT registered in ``config.SUPPORTED_PROTOCOLS`` /
``profiles.PROTOCOL_MODULES``. Instead the connector carries its own tiny,
immutable :class:`BasTarget` (built from tool arguments, not the YAML endpoint
config) and assembles its own stateless-HTTP ``bas_session`` right here via the
shared :func:`make_session` lifecycle — the same factory HART / IO-Link use,
reused without leaking a vendor name into core.

The "connection" is stateless HTTP: build resolves the base URL + dialect; there
is no connect/close. Failures translate to a teaching ``OTConnectionError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from iaiops.connectors.bas.client import BasClient
from iaiops.connectors.bas.dialects import UnknownVendorError, get_dialect
from iaiops.core.runtime.config import DEFAULT_TIMEOUT_S
from iaiops.core.runtime.session_factory import OTConnectionError, make_session

# The connector-local protocol tag the local session guards on. It is NOT a
# public wire protocol (never added to SUPPORTED_PROTOCOLS) — only this session
# accepts it, so the shared make_session guard still works unchanged.
_BAS_PROTOCOL = "bas"


@dataclass(frozen=True)
class BasTarget:
    """Immutable per-call BAS controller target (from tool args, not YAML config).

    Mirrors the shape :func:`make_session` expects (``name`` + ``protocol``) so
    the shared lifecycle guards/translates exactly as for a real endpoint,
    without a YAML ``TargetConfig`` (which would require registering ``bas`` as a
    core protocol — this layer is edition-scoped, so it does not).
    """

    name: str
    base_url: str
    vendor: str
    token: str = field(default="", repr=False)  # bearer secret — keep out of repr
    timeout_s: float = DEFAULT_TIMEOUT_S
    verify_tls: bool = True
    protocol: str = _BAS_PROTOCOL


def _build_bas_client(target: BasTarget) -> BasClient:
    """Construct the stateless HTTP client for ``target``. Module-level patch point."""
    base = (target.base_url or "").rstrip("/")
    if not base:
        raise OTConnectionError(
            f"BAS controller '{target.name}' has no base_url. Pass the controller "
            f"REST base, e.g. 'https://<controller-host>/api'.",
            endpoint=target.name,
            protocol=_BAS_PROTOCOL,
        )
    try:
        dialect = get_dialect(target.vendor)
    except UnknownVendorError as exc:
        raise OTConnectionError(str(exc), endpoint=target.name, protocol=_BAS_PROTOCOL) from exc
    return BasClient(
        base_url=base,
        dialect=dialect,
        token=target.token,
        timeout_s=target.timeout_s,
        verify_tls=target.verify_tls,
    )


def _translate_bas(exc: Exception, target: BasTarget) -> OTConnectionError:
    """Map an HTTP/parse failure to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    return OTConnectionError(
        f"BAS controller operation on '{target.name}' ({target.base_url}) failed: "
        f"{detail}. Check the base URL, that the controller's REST/oBIX-JSON "
        f"interface is reachable, and that the bearer token/secret is valid.",
        endpoint=target.base_url or target.name,
        protocol=_BAS_PROTOCOL,
    )


# Stateless HTTP (like IO-Link/MTConnect): build resolves base URL + dialect; no
# connect/close. The session still guards the protocol and translates failures.
bas_session = make_session(
    protocol=_BAS_PROTOCOL,
    build=lambda target: _build_bas_client(target),
    translate=_translate_bas,
    name="bas_session",
)


__all__ = ["BasTarget", "_build_bas_client", "_translate_bas", "bas_session"]
