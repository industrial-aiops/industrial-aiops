"""BACnet/IP transport: BAC0 network build + error translation (from connection.py).

The assembled ``bacnet_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`, built INSIDE the
translated block because ``BAC0.lite(ip=...)`` binds UDP/47808 in the
constructor); tests keep monkeypatching ``connection._build_bacnet_network``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError

BACNET_DEFAULT_PORT = 47808


def _build_bacnet_network(target: TargetConfig) -> Any:
    """Construct (and connect) a BAC0 network bound to the local interface.

    ``BAC0`` (over bacpypes3) is an OPTIONAL extra (``pip install iaiops[bacnet]``)
    imported LAZILY. Modern BAC0 (2024+) is async-first: ``BAC0.lite(ip=...)`` must
    be built inside a running event loop and ``who_is`` / ``read`` / ``readRange``
    are coroutines. So we construct BAC0 on a dedicated background loop and return
    a synchronous facade (:class:`~iaiops.core.runtime.bacnet_async.BacnetSyncNetwork`)
    that marshals every call onto that loop — the same bridge pattern asyncua's sync
    client uses. This keeps the broad pin (``BAC0>=2023.6,<2026``) and the sync ops
    unchanged: sync-era and async-first builds both work through the facade.

    ``lite(ip=...)`` binds THIS machine's BACnet/IP interface (``host``, optionally
    ``ip/mask``); remote devices are addressed per call. Module-level so tests
    monkeypatch it with a fake network object.
    """
    try:
        import BAC0
    except ImportError as exc:  # pragma: no cover — only without BAC0
        raise OTConnectionError(
            "The 'BAC0' package is not installed. BACnet is an OPTIONAL extra: "
            "'pip install iaiops[bacnet]'.",
            endpoint=target.name,
            protocol="bacnet",
        ) from exc
    if not target.host:
        raise OTConnectionError(
            f"BACnet endpoint '{target.name}' has no host. Add 'host: <local-ip>' "
            f"(THIS machine's BACnet/IP interface, optionally '<ip>/<mask>').",
            endpoint=target.name,
            protocol="bacnet",
        )
    from iaiops.core.runtime.bacnet_async import build_sync_network

    lite = getattr(BAC0, "lite", None) or BAC0.connect
    return build_sync_network(lite, target.host)


def _close_bacnet(net: Any) -> None:
    """Disconnect the BAC0 network when the facade exposes ``disconnect()``."""
    disconnect = getattr(net, "disconnect", None)
    if callable(disconnect):
        disconnect()


def _translate_endpoint_error(
    exc: Exception, target: TargetConfig, protocol: str, port: int
) -> OTConnectionError:
    """Map a preview/optional-protocol library/OS exception (BACnet) to a teaching error."""
    detail = str(exc).strip()[:200]
    where = f"{target.host}:{port}"
    return OTConnectionError(
        f"{protocol.upper()} operation on '{target.name}' ({where}) failed: {detail}. "
        f"Check host/port/addressing and that the device is reachable. Preview — "
        f"validate against live gear or a protocol simulator.",
        endpoint=where,
        protocol=protocol,
    )


def _translate_bacnet(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a BAC0/OS exception to a teaching ``OTConnectionError``."""
    return _translate_endpoint_error(exc, target, "bacnet", target.port or BACNET_DEFAULT_PORT)


__all__ = [
    "BACNET_DEFAULT_PORT",
    "_build_bacnet_network",
    "_close_bacnet",
    "_translate_bacnet",
    "_translate_endpoint_error",
]
