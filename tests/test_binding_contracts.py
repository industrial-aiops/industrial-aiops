"""Library-API CONTRACT tests for the preview/待核实 bindings.

The base test-suite mocks every protocol library, so a driver can drift from (or
fabricate) the real library API and still pass — exactly how the BACnet ``whois``
typo and the wrong ``iec61850`` distribution slipped in. These tests close that
gap: when the REAL optional library is importable, assert that every symbol/method
the driver actually calls exists on it. They ``importorskip`` so the base suite
(no extras installed) skips them cleanly, and a CI lane that installs an extra
runs them for real. Each is marked ``integration``.

Verified live 2026-06-30: apache-iotdb (container round-trip), BAC0 (who_is). The
energy bindings (c104 / pydnp3 / pyiec61850) moved to the iaiops-energy repo, which
carries their contract tests. See docs/CHINA.md / docs/ROADMAP.md.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_bacnet_bac0_surface() -> None:
    """BAC0.lite must expose every method the bacnet ops call.

    Reads use who_is/read; the bounded COV capture uses cov/cancel_cov; the
    trend-log read uses readRange; teardown uses disconnect. A fabricated name
    here = AttributeError on live gear (the exact bug class this repo fixes).
    """
    bac0 = pytest.importorskip("BAC0")
    lite = bac0.lite
    for method in ("who_is", "read", "cov", "cancel_cov", "readRange", "disconnect"):
        assert hasattr(lite, method), f"BAC0.lite lacks {method!r} — bacnet ops call it"
    # Guard against a regression to the fabricated name.
    assert not hasattr(lite, "whois"), "BAC0.lite has no 'whois'; ops must use 'who_is'"


def test_bacnet_bac0_cov_signature() -> None:
    """BAC0.lite.cov must accept the keyword args the COV op passes."""
    import inspect

    bac0 = pytest.importorskip("BAC0")
    params = inspect.signature(bac0.lite.cov).parameters
    for kw in ("address", "objectID", "lifetime", "confirmed", "callback"):
        assert kw in params, f"BAC0.lite.cov lacks {kw!r} — bacnet_cov_subscribe passes it"


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
