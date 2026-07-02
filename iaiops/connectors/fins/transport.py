"""Omron FINS transport: client build + error translation (B1 pattern).

The assembled ``fins_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests
monkeypatch ``connection._build_fins_client``. The client itself is the
in-repo stdlib implementation in :mod:`iaiops.connectors.fins.client` —
no third-party library, so there is no import guard / extra to check.
"""

from __future__ import annotations

from iaiops.connectors.fins.client import (
    DEFAULT_FINS_PORT,
    FinsTcpClient,
    FinsUdpClient,
)
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_fins_client(target: TargetConfig) -> FinsUdpClient | FinsTcpClient:
    """Construct (but do not connect) a FINS client for ``target``.

    Module-level so tests can monkeypatch it. Selects FINS/TCP when the
    endpoint's ``transport`` is ``tcp``, else FINS/UDP (the protocol default).
    """
    if not target.host:
        raise OTConnectionError(
            f"FINS endpoint '{target.name}' has no host. Add 'host: <plc-ip>' to "
            f"its config entry (Omron CS/CJ/CP/NX Ethernet unit; port defaults "
            f"to {DEFAULT_FINS_PORT}; transport udp|tcp).",
            endpoint=target.name,
            protocol="fins",
        )
    if target.transport == "tcp":
        return FinsTcpClient(
            target.host, target.port or DEFAULT_FINS_PORT, timeout_s=target.timeout_s
        )
    # UDP default: destination node defaults to the PLC IP's last octet (the
    # common automatic-address-conversion convention, 待核实 per site).
    return FinsUdpClient(
        target.host, target.port or DEFAULT_FINS_PORT, timeout_s=target.timeout_s
    )


def _connect_fins(client: FinsUdpClient | FinsTcpClient, target: TargetConfig) -> None:
    """Open the FINS transport (UDP: bind socket; TCP: connect + node handshake)."""
    client.connect()


def _translate_fins(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a FINS client failure to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    transport = target.transport or "udp"
    endpoint = f"{target.host}:{target.port or DEFAULT_FINS_PORT}/{transport}"
    return OTConnectionError(
        f"FINS operation on '{target.name}' ({endpoint}) failed: {detail}. Check "
        f"the host/port, that the Omron Ethernet unit's FINS/{transport.upper()} "
        f"service is enabled (default UDP {DEFAULT_FINS_PORT}), and the node "
        f"addressing (UDP defaults the destination node to the PLC IP's last "
        f"octet). Live-PLC behaviour is 待核实 — self-test against the in-repo "
        f"mock responder (tests/test_fins.py).",
        endpoint=endpoint,
        protocol="fins",
    )


__all__ = ["_build_fins_client", "_connect_fins", "_translate_fins"]
