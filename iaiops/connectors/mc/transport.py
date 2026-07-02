"""Mitsubishi MC transport: pymcprotocol build + error translation (from connection.py).

The assembled ``mc_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_mc_client``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_mc_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pymcprotocol Type3E client for ``target``.

    Module-level so tests can monkeypatch it. pymcprotocol is pure Python.
    """
    try:
        import pymcprotocol
    except ImportError as exc:  # pragma: no cover — exercised only without the lib
        raise OTConnectionError(
            "The 'pymcprotocol' package is not installed. Install the "
            "Mitsubishi MC connector: 'pip install iaiops[mc]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"MC endpoint '{target.name}' has no host. Add 'host: <ip>' to its "
            f"config entry (plctype Q|L|QnA|iQ-R|iQ-L).",
            endpoint=target.name,
            protocol="mc",
        )
    client = pymcprotocol.Type3E(plctype=target.plctype or "Q")
    # pymcprotocol (0.3.x) has no constructor timeout; ``soc_timeout`` is its
    # public socket-timeout knob (seconds), applied via settimeout() in connect().
    client.soc_timeout = target.timeout_s
    return client


def _connect_mc(client: Any, target: TargetConfig) -> None:
    """Connect a pymcprotocol client (MC 3E binary, default port 5007)."""
    client.connect(target.host, target.port or 5007)


def _translate_mc(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pymcprotocol exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host}:{target.port or 5007} ({target.plctype})"
    return OTConnectionError(
        f"MC operation on '{target.name}' ({endpoint}) failed: {detail}. Check the "
        f"host/port, the MC 3E binary 'SLMP/MC' server is open on the Ethernet "
        f"module, and the plctype. Point at a GX Simulator / MC sim to test.",
        endpoint=endpoint,
        protocol="mc",
    )


__all__ = ["_build_mc_client", "_connect_mc", "_translate_mc"]
