"""EtherCAT transport: pysoem master build + error translation (from connection.py).

The assembled ``ethercat_master`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_ethercat_master``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_ethercat_master(target: TargetConfig) -> Any:
    """Construct (but do not open) a pysoem Master for ``target``.

    ``pysoem`` is an OPTIONAL dependency (``pip install iaiops[ethercat]``).
    It is imported LAZILY here so the package installs and imports cleanly
    WITHOUT it — every EtherCAT tool then degrades to a teaching error instead
    of crashing. EtherCAT is hard-real-time: it needs **Linux + root/CAP_NET_RAW
    + a dedicated NIC + real slave hardware**; there is NO software simulator and
    macOS is effectively unsupported. Module-level so tests monkeypatch it with a
    fake master (the only way to exercise this without a live bus).
    """
    try:
        import pysoem
    except ImportError as exc:  # pragma: no cover — exercised only without pysoem
        raise OTConnectionError(
            "The 'pysoem' package is not installed. EtherCAT is an OPTIONAL extra: "
            "'pip install iaiops[ethercat]'. It also requires Linux, root or "
            "CAP_NET_RAW, a dedicated NIC, and real EtherCAT slaves on the bus — "
            "there is NO software simulator and macOS is unsupported.",
            endpoint=target.name,
            protocol="ethercat",
        ) from exc

    nic = target.nic or target.host
    if not nic:
        raise OTConnectionError(
            f"EtherCAT endpoint '{target.name}' has no NIC. Add 'nic: <iface>' "
            f"(e.g. 'nic: eth1') — the dedicated interface cabled to the EtherCAT "
            f"bus — to its config entry.",
            endpoint=target.name,
            protocol="ethercat",
        )
    return pysoem.Master()


def _open_ethercat(master: Any, target: TargetConfig) -> None:
    """Open the master on the configured NIC (``nic`` falling back to ``host``)."""
    master.open(target.nic or target.host)


def _prepare_ethercat(master: Any, target: TargetConfig, *, map_pdo: bool = False) -> None:
    """Enumerate the bus; optionally map the process-data image.

    ``config_init`` returns the number of slaves found on the bus (0 = none).
    When ``map_pdo`` is True, ``config_map`` makes the process-data image
    addressable (needed for PDO reads / OP-state).
    """
    master.config_init(False)
    if map_pdo:
        master.config_map()


def _translate_ethercat(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a pysoem / OS exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    nic = target.nic or target.host or "?"
    lowered = detail.lower()
    if isinstance(exc, PermissionError) or "permitted" in lowered or "permission" in lowered:
        return OTConnectionError(
            f"EtherCAT master '{target.name}' (nic={nic}) lacks raw-socket permission. "
            f"Run as root or grant CAP_NET_RAW (e.g. 'sudo setcap cap_net_raw+ep "
            f"$(readlink -f $(which python))'). EtherCAT needs Linux + a dedicated "
            f"NIC + real slaves. {detail}",
            endpoint=nic,
            protocol="ethercat",
        )
    return OTConnectionError(
        f"EtherCAT master '{target.name}' (nic={nic}) failed: {detail}. Check the NIC "
        f"name (e.g. eth1), that you are root / have CAP_NET_RAW, the cabling, and "
        f"that real EtherCAT slaves are on the bus. There is NO software simulator "
        f"(macOS unsupported) — validate on Linux with hardware.",
        endpoint=nic,
        protocol="ethercat",
    )


__all__ = [
    "_build_ethercat_master",
    "_open_ethercat",
    "_prepare_ethercat",
    "_translate_ethercat",
]
