"""EtherNet/IP transport: pycomm3 build + error translation (from connection.py).

The assembled ``eip_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_eip_client``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_eip_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a pycomm3 LogixDriver for ``target``.

    Module-level so tests can monkeypatch it with a fake driver. pycomm3 is pure
    Python (no native deps). The CIP path is ``host`` or ``host/slot`` (the slot
    is the controller's chassis slot — 0 for most CompactLogix, the CPU slot for
    a ControlLogix chassis).
    """
    try:
        from pycomm3 import LogixDriver
    except ImportError as exc:  # pragma: no cover — exercised only without pycomm3
        raise OTConnectionError(
            "The 'pycomm3' package is not installed. Install the EtherNet/IP "
            "connector: 'pip install iaiops[eip]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"EtherNet/IP endpoint '{target.name}' has no host. Add 'host: <ip>' to "
            f"its config entry (and 'slot:' for a ControlLogix chassis CPU slot).",
            endpoint=target.name,
            protocol="ethernetip",
        )
    path = f"{target.host}/{target.slot}" if target.slot else target.host
    driver = LogixDriver(path)
    # pycomm3 (1.2.x) ignores constructor kwargs for this; ``socket_timeout`` is
    # its public property for the socket open/receive timeout (seconds).
    driver.socket_timeout = target.timeout_s
    return driver


def _translate_eip(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pycomm3 exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host} slot={target.slot}"
    return OTConnectionError(
        f"EtherNet/IP operation on '{target.name}' ({endpoint}) failed: {detail}. "
        f"Check the host, the controller slot (0 for CompactLogix, the CPU slot for "
        f"ControlLogix), that EtherNet/IP (TCP 44818) is reachable, and that this is "
        f"a Logix controller (PLC-5/SLC PCCC is not supported). Point at a CIP/Logix "
        f"simulator to test.",
        endpoint=endpoint,
        protocol="ethernetip",
    )


__all__ = ["_build_eip_client", "_translate_eip"]
