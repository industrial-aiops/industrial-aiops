"""SECS/GEM transport: secsgem host build + error translation (from connection.py).

The assembled ``secsgem_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_secsgem_host``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import DEFAULT_SECSGEM_PORT, TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_secsgem_host(target: TargetConfig) -> Any:
    """Construct (but do not enable) a secsgem GEM *host* handler for ``target``.

    We are the HOST connecting (HSMS ACTIVE) to the equipment's passive port.
    ``secsgem`` is an OPTIONAL extra (``pip install iaiops[secsgem]``). Module-level
    so tests can monkeypatch it with a fake handler.
    """
    try:
        from secsgem.gem import GemHostHandler
        from secsgem.hsms import DeviceType, HsmsConnectMode, HsmsSettings
    except ImportError as exc:  # pragma: no cover — exercised only without secsgem
        raise OTConnectionError(
            "The 'secsgem' package is not installed. Install the SECS/GEM "
            "connector: 'pip install iaiops[secsgem]'."
        ) from exc

    settings = HsmsSettings(
        address=target.host,
        port=target.port or DEFAULT_SECSGEM_PORT,
        connect_mode=HsmsConnectMode.ACTIVE,
        device_type=DeviceType.HOST,
        session_id=target.unit_id,
    )
    return GemHostHandler(settings)


def _require_secsgem_host(target: TargetConfig) -> None:
    """Validate the endpoint has a host BEFORE building (teaching error if not)."""
    if not target.host:
        raise OTConnectionError(
            f"SECS/GEM endpoint '{target.name}' has no host. Add 'host: <ip>' and "
            f"optionally 'port: 5000' (HSMS default) to its config entry.",
            endpoint=target.name,
            protocol="secsgem",
        )


def _wait_communicating(handler: Any, target: TargetConfig, *, timeout_s: float = 10.0) -> None:
    """Block until the GEM link reaches the communicating state (or teach)."""
    if not handler.waitfor_communicating(timeout_s):
        raise OTConnectionError(
            f"SECS/GEM '{target.name}' did not reach the communicating state "
            f"within {timeout_s}s (equipment offline or not PASSIVE/listening).",
            endpoint=target.name,
            protocol="secsgem",
        )


def _translate_secsgem(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a secsgem/HSMS exception to a teaching ``OTConnectionError``."""
    name = type(exc).__name__
    detail = str(exc).strip()[:200]
    where = f"{target.host}:{target.port or DEFAULT_SECSGEM_PORT}"
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)) or "timeout" in name.lower():
        return OTConnectionError(
            f"Could not reach SECS/GEM equipment '{target.name}' ({where}). Check the "
            f"host/port (HSMS default 5000), that the equipment is online and configured "
            f"as PASSIVE/listening, and the session (device) id. {detail}",
            endpoint=where,
            protocol="secsgem",
        )
    return OTConnectionError(
        f"SECS/GEM operation on '{target.name}' ({where}) failed: {detail}",
        endpoint=where,
        protocol="secsgem",
    )


__all__ = [
    "_build_secsgem_host",
    "_require_secsgem_host",
    "_translate_secsgem",
    "_wait_communicating",
]
