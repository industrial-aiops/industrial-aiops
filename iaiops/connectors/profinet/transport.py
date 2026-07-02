"""PROFINET-DCP transport: pnio-dcp build + error translation (from connection.py).

The assembled ``profinet_dcp`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`, built INSIDE the
translated block because ``DCP(ip)`` binds an L2 raw socket in its constructor);
tests keep monkeypatching ``connection._build_profinet_dcp``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_profinet_dcp(target: TargetConfig) -> Any:
    """Construct a pnio-dcp ``DCP`` bound to the local interface for ``target``.

    ``pnio-dcp`` is an OPTIONAL dependency (``pip install iaiops[profinet]``),
    imported LAZILY so the package installs/imports without it. PROFINET-DCP is a
    layer-2 (raw Ethernet) discovery protocol: the ``DCP`` is bound to the LOCAL
    interface identified by its IP (``host``), and an IdentifyAll broadcast finds
    every PROFINET station on that segment. It needs raw-socket access
    (root / admin / CAP_NET_RAW). This is discovery + identify ONLY — no RT cyclic
    process data. Module-level so tests monkeypatch it with a fake DCP.
    """
    try:
        from pnio_dcp import DCP
    except ImportError as exc:  # pragma: no cover — exercised only without pnio-dcp
        raise OTConnectionError(
            "The 'pnio-dcp' package is not installed. PROFINET is an OPTIONAL extra: "
            "'pip install iaiops[profinet]'. It also needs layer-2 raw-socket access "
            "(root/admin/CAP_NET_RAW) on the NIC connected to the PROFINET subnet. "
            "Read-only DCP discovery/identify only — no RT cyclic data.",
            endpoint=target.name,
            protocol="profinet",
        ) from exc

    ip = target.host or target.nic
    if not ip:
        raise OTConnectionError(
            f"PROFINET endpoint '{target.name}' has no host. Add 'host: <local-ip>' "
            f"— the IP of THIS machine's interface on the PROFINET subnet (the DCP "
            f"broadcast goes out on it) — to its config entry.",
            endpoint=target.name,
            protocol="profinet",
        )
    return DCP(ip)


def _close_profinet(dcp: Any) -> None:
    """Close the DCP handle when it exposes ``close()`` (older builds may not)."""
    close = getattr(dcp, "close", None)
    if callable(close):
        close()


def _translate_profinet(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pnio-dcp / OS exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    ip = target.host or target.nic or "?"
    lowered = detail.lower()
    if isinstance(exc, PermissionError) or "permitted" in lowered or "permission" in lowered:
        return OTConnectionError(
            f"PROFINET-DCP on '{target.name}' (local ip={ip}) lacks raw-socket "
            f"permission. Run as root/admin or grant CAP_NET_RAW. PROFINET-DCP is "
            f"layer-2 and needs the NIC on the PROFINET subnet. {detail}",
            endpoint=ip,
            protocol="profinet",
        )
    return OTConnectionError(
        f"PROFINET-DCP on '{target.name}' (local ip={ip}) failed: {detail}. Check the "
        f"host is THIS machine's IP on the PROFINET subnet, that you have raw-socket "
        f"access, and that stations are powered on the segment. Validate against a "
        f"PROFINET device or a DCP simulator.",
        endpoint=ip,
        protocol="profinet",
    )


__all__ = ["_build_profinet_dcp", "_close_profinet", "_translate_profinet"]
