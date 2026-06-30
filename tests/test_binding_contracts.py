"""Library-API CONTRACT tests for the preview/待核实 bindings.

The base test-suite mocks every protocol library, so a driver can drift from (or
fabricate) the real library API and still pass — exactly how the BACnet ``whois``
typo and the wrong ``iec61850`` distribution slipped in. These tests close that
gap: when the REAL optional library is importable, assert that every symbol/method
the driver actually calls exists on it. They ``importorskip`` so the base suite
(no extras installed) skips them cleanly, and a CI lane that installs an extra —
or a verification container with ``iaiops[all]`` + energy extras — runs them for
real. Each is marked ``integration``.

Verified live 2026-06-30: c104 (loopback), apache-iotdb (container round-trip),
BAC0 (who_is), pyiec61850 (symbol surface). See docs/CHINA.md / docs/ROADMAP.md.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_bacnet_bac0_surface() -> None:
    """BAC0.lite must expose the methods the bacnet ops call (who_is/read/disconnect)."""
    bac0 = pytest.importorskip("BAC0")
    lite = bac0.lite
    for method in ("who_is", "read", "disconnect"):
        assert hasattr(lite, method), f"BAC0.lite lacks {method!r} — bacnet ops call it"
    # Guard against a regression to the fabricated name.
    assert not hasattr(lite, "whois"), "BAC0.lite has no 'whois'; ops must use 'who_is'"


def test_iotdb_session_surface() -> None:
    """apache-iotdb Session + TSDataType must match the IoTDB sink's calls."""
    session_mod = pytest.importorskip("iotdb.Session")
    consts = pytest.importorskip("iotdb.utils.IoTDBConstants")
    session_cls = session_mod.Session
    for method in ("open", "insert_record", "close"):
        assert hasattr(session_cls, method), f"iotdb Session lacks {method!r}"
    assert hasattr(consts.TSDataType, "DOUBLE")


def test_tdengine_taos_surface() -> None:
    """taospy native ``taos`` must expose connect() (TDengine sink calls it).

    ``taos`` imports the native libtaos client at import time; on a host without
    that C library it raises ``InterfaceError`` (not ImportError), so skip then —
    the symbol check only means anything where libtaos is actually present.
    """
    try:
        import taos
    except ImportError:
        pytest.skip("taospy not installed")
    except Exception as exc:  # noqa: BLE001 — InterfaceError: libtaos absent
        pytest.skip(f"libtaos client library not loadable: {exc}")
    assert hasattr(taos, "connect"), "taos.connect missing — TDengine sink needs it"


def test_iec104_c104_surface() -> None:
    """c104 must expose Client / Init.INTERROGATION (iec104 connection builder)."""
    c104 = pytest.importorskip("c104")
    assert hasattr(c104, "Client")
    assert hasattr(getattr(c104, "Init", None), "INTERROGATION")


def test_iec61850_pyiec61850_symbols() -> None:
    """The libiec61850 SWIG binding (pyiec61850) must expose every symbol the adapter calls.

    Regression guard for the wrong-distribution bug: the unrelated PyPI ``iec61850``
    package exposes NONE of these, so importing it here would fail the suite.
    """
    lib = pytest.importorskip("pyiec61850")
    for sym in (
        "IedConnection_create", "IedConnection_connect", "IedConnection_close",
        "IedConnection_destroy", "IedConnection_getLogicalDeviceList",
        "IedConnection_getDataDirectory", "IedConnection_readObject",
        "FunctionalConstraint_fromString", "MmsValue_toFloat", "MmsValue_delete",
    ):
        assert hasattr(lib, sym), f"pyiec61850 lacks {sym!r} — iec61850 driver calls it"


def test_dnp3_pydnp3_symbols() -> None:
    """pydnp3/opendnp3 must expose the manager/master symbols the DNP3 adapter wires."""
    pytest.importorskip("pydnp3")
    from pydnp3 import asiodnp3, asiopal, opendnp3
    assert hasattr(asiodnp3, "DNP3Manager")
    assert hasattr(asiodnp3, "MasterStackConfig")
    assert hasattr(asiopal, "ChannelRetry")
    assert hasattr(opendnp3, "ClassField")


def test_iec104_loopback_session() -> None:
    """Real IEC-104 link: an in-process c104 server + the actual iec104_session.

    Exercises ``_build_iec104_client`` → ``client.start()`` → ``conn.is_connected``
    against a live (loopback) RTU — the binding path that mocks can't cover.
    """
    c104 = pytest.importorskip("c104")
    from iaiops.core.runtime.config import TargetConfig
    from iaiops.core.runtime.connection import iec104_session

    server = c104.Server(ip="127.0.0.1", port=24040)
    station = server.add_station(common_address=47)
    point = station.add_point(io_address=11, type=c104.Type.M_ME_NC_1)
    point.value = 1.5
    server.start()
    try:
        target = TargetConfig(
            name="rtu-loop", protocol="iec104", host="127.0.0.1", port=24040,
        )
        with iec104_session(target, timeout_s=8.0) as (client, conn):
            assert conn.is_connected is True
    finally:
        server.stop()
