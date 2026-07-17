"""EtherNet/IP transport: pycomm3 build + error translation (from connection.py).

The assembled ``eip_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_eip_client``.

pycomm3 ships three CIP drivers that this connector selects between via the
target's ``plctype`` field (a per-endpoint config key, also overridable per call):

  * ``logix`` (default) — :class:`pycomm3.LogixDriver`: ControlLogix / CompactLogix
    / GuardLogix symbolic tag access (``Program:Main.Speed``). Path ``host/slot``.
  * ``slc`` — :class:`pycomm3.SLCDriver`: **PCCC** data-table access for the
    Allen-Bradley PLC-5 / SLC-500 / MicroLogix families (``N7:0`` integer,
    ``B3:0/0`` bit, ``F8:0`` float, ``T4:0.ACC`` / ``C5:0.ACC`` timer/counter).
    Native-Ethernet / ENI-bridged, addressed by IP only (no chassis slot).
  * ``micro800`` — :class:`pycomm3.LogixDriver` (Micro800 is auto-detected by
    pycomm3): Micro820/850/870 symbolic variables, IP only (no chassis slot).

Real PLC-5 / SLC-500 / MicroLogix / Micro800 hardware behaviour is 待核实 — the
driver-selection and read/write paths are exercised against mocked pycomm3
drivers only.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError

# plctype → driver-kind resolution. ``TargetConfig.plctype`` is a shared field
# (its default ``"Q"`` is the Mitsubishi-MC family selector); for EtherNet/IP any
# value that is not an explicit PCCC or Micro800 alias resolves to the Logix
# default, so a plain EIP endpoint with no ``plctype:`` stays Logix.
_EIP_SLC_ALIASES = frozenset(
    {"slc", "slc500", "slc-500", "plc5", "plc-5", "pccc", "micrologix", "mlx", "df1"}
)
_EIP_MICRO800_ALIASES = frozenset(
    {"micro800", "micro8xx", "m800", "micro820", "micro850", "micro870"}
)


def _resolve_eip_kind(plctype: str) -> str:
    """Map a ``plctype`` string to an EtherNet/IP driver kind.

    Returns ``'slc'`` for PCCC aliases (PLC-5/SLC-500/MicroLogix → SLCDriver),
    ``'micro800'`` for Micro8xx aliases (→ LogixDriver, no chassis slot), and
    ``'logix'`` for everything else including the shared ``''`` / ``'Q'`` default.
    """
    key = (plctype or "").strip().lower()
    if key in _EIP_SLC_ALIASES:
        return "slc"
    if key in _EIP_MICRO800_ALIASES:
        return "micro800"
    return "logix"


def _eip_path(target: TargetConfig, kind: str) -> str:
    """CIP connection path for the driver kind.

    Logix routes through the chassis (``host`` or ``host/slot``). SLC/PCCC and
    Micro800 are single-unit / native-Ethernet endpoints addressed by IP only —
    a backplane-bridged PCCC route (via a ControlLogix gateway) is 待核实.
    """
    if kind == "logix" and target.slot:
        return f"{target.host}/{target.slot}"
    return target.host


def _build_eip_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) the pycomm3 driver selected by ``plctype``.

    Module-level so tests can monkeypatch it with a fake driver. pycomm3 is pure
    Python (no native deps). ``logix`` → LogixDriver (chassis ``host/slot``);
    ``slc`` → SLCDriver (PCCC, IP only); ``micro800`` → LogixDriver with
    ``init_program_tags=False`` (Micro8xx has no program scope; pycomm3
    auto-detects the family and drops multi-request packets/unconnected sends).
    """
    kind = _resolve_eip_kind(target.plctype)
    try:
        from pycomm3 import LogixDriver, SLCDriver
    except ImportError as exc:  # pragma: no cover — exercised only without pycomm3
        raise OTConnectionError(
            "The 'pycomm3' package is not installed. Install the EtherNet/IP "
            "connector: 'pip install iaiops[eip]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"EtherNet/IP endpoint '{target.name}' has no host. Add 'host: <ip>' to "
            f"its config entry (and, for a ControlLogix chassis, 'slot:' the CPU slot; "
            f"a PLC-5/SLC/MicroLogix or Micro800 uses the IP only).",
            endpoint=target.name,
            protocol="ethernetip",
        )
    path = _eip_path(target, kind)
    if kind == "slc":
        driver: Any = SLCDriver(path)
    elif kind == "micro800":
        driver = LogixDriver(path, init_program_tags=False)
    else:
        driver = LogixDriver(path)
    # pycomm3 (1.2.x) ignores constructor kwargs for this; ``socket_timeout`` is
    # its public property for the socket open/receive timeout (seconds) — present
    # on both LogixDriver and SLCDriver.
    driver.socket_timeout = target.timeout_s
    return driver


def _translate_eip(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pycomm3 exception to a teaching ``OTConnectionError`` (kind-aware)."""
    detail = str(exc).strip()[:200]
    kind = _resolve_eip_kind(target.plctype)
    endpoint = f"{target.host} slot={target.slot} plctype={kind}"
    if kind == "slc":
        hint = (
            "Check the host, that EtherNet/IP (TCP 44818) is reachable, that this is a "
            "PLC-5 / SLC-500 / MicroLogix reachable over PCCC (an SLC-5/05, a "
            "1761-NET-ENI bridge, or a MicroLogix 1100/1400 — addressed by IP, no "
            "chassis slot), and that you used a data-table address (N7:0 integer, "
            "B3:0/0 bit, F8:0 float, T4:0.ACC / C5:0.ACC). Point at an SLC/PCCC "
            "simulator to test."
        )
    elif kind == "micro800":
        hint = (
            "Check the host (a Micro800 uses the IP only — no chassis slot), that "
            "EtherNet/IP (TCP 44818) is reachable, and that the symbolic variable name "
            "exists (Micro820/850/870). Point at a Micro800 simulator to test."
        )
    else:
        hint = (
            "Check the host, the controller slot (0 for CompactLogix, the CPU slot for "
            "ControlLogix), that EtherNet/IP (TCP 44818) is reachable, and that this is "
            "a Logix controller. For a PLC-5/SLC-500/MicroLogix set plctype='slc' (PCCC "
            "data tables); for a Micro820/850/870 set plctype='micro800'. Point at a "
            "CIP/Logix simulator to test."
        )
    return OTConnectionError(
        f"EtherNet/IP operation on '{target.name}' ({endpoint}) failed: {detail}. {hint}",
        endpoint=endpoint,
        protocol="ethernetip",
    )


__all__ = ["_build_eip_client", "_eip_path", "_resolve_eip_kind", "_translate_eip"]
