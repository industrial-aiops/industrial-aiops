"""S7comm transport: pyS7 client build + error translation (from connection.py).

The assembled ``s7_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_s7_client``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_s7_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pyS7 S7Client for ``target``.

    Module-level so tests can monkeypatch it with a fake client. pyS7 is pure
    Python (no native libsnap7), so the venv installs cleanly everywhere.
    """
    try:
        from pyS7 import S7Client
    except ImportError as exc:  # pragma: no cover — exercised only without pyS7
        raise OTConnectionError(
            "The 'pyS7' package is not installed. Install the S7comm "
            "connector: 'pip install iaiops[s7]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"S7 endpoint '{target.name}' has no host. Add 'host: <ip>' to its "
            f"config entry (rack/slot default 0/1 for S7-1200/1500).",
            endpoint=target.name,
            protocol="s7",
        )
    # pyS7's socket timeout (seconds) makes a dead PLC fail fast instead of
    # hanging on the OS TCP timeout.
    return S7Client(
        target.host,
        rack=target.rack,
        slot=target.slot,
        port=target.port or 102,
        timeout=target.timeout_s,
    )


def _translate_s7(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pyS7 exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host}:{target.port or 102} rack={target.rack} slot={target.slot}"
    return OTConnectionError(
        f"S7 operation on '{target.name}' ({endpoint}) failed: {detail}. Check the "
        f"host, rack/slot (0/1 for S7-1200/1500, 0/2 for many S7-300/400), and that "
        f"PUT/GET access is enabled on the CPU. Point at a local S7 simulator to test.",
        endpoint=endpoint,
        protocol="s7",
    )


__all__ = ["_build_s7_client", "_translate_s7"]
