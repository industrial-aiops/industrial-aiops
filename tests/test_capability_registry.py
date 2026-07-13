"""Drift guard for the per-protocol capability registry (the refactor's payoff).

The registry (``iaiops.core.runtime.capabilities.REGISTRY``) replaced ~7 parallel
if/elif ladders — doctor probe / doctor ``where`` / dataflow connect / per-ref
read / CoV monitor read / session routing — each of which historically supported
a DIFFERENT subset of protocols (which is how "hart missing from the doctor
probe" crept in).

These assertions make a FORGOTTEN registration fail CI loudly instead of
silently mis-defaulting at runtime: every ``SUPPORTED_PROTOCOLS`` entry must have
a record, every capability must be either a real callable or the explicit
``UNSUPPORTED`` sentinel, and the doctor's informational-probe table must stay in
lockstep with the registry's ``probe_style``.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.capabilities import (
    PROBE_HARD,
    PROBE_INFORMATIONAL,
    PROBE_OPCUA,
    REGISTRY,
    UNSUPPORTED,
    ProtocolCapabilities,
    get_capabilities,
    session_supported_protocols,
)
from iaiops.core.runtime.config import SUPPORTED_PROTOCOLS

_VALID_STYLES = {PROBE_HARD, PROBE_OPCUA, PROBE_INFORMATIONAL}

# Every capability field except the always-present ``where_hint`` may be UNSUPPORTED.
_SENTINEL_FIELDS = (
    "doctor_probe",
    "diagnose_connect",
    "read_ref",
    "monitor_read",
    "session_builder",
)


@pytest.mark.unit
@pytest.mark.parametrize("protocol", SUPPORTED_PROTOCOLS)
def test_every_supported_protocol_has_a_registry_entry(protocol: str) -> None:
    cap = get_capabilities(protocol)
    assert cap is not None, (
        f"protocol {protocol!r} is in SUPPORTED_PROTOCOLS but has no capability "
        f"registry entry — add one to iaiops.core.runtime.capabilities.REGISTRY."
    )
    assert isinstance(cap, ProtocolCapabilities)


@pytest.mark.unit
def test_registry_has_no_phantom_protocols() -> None:
    """No registry key without a matching SUPPORTED_PROTOCOLS entry."""
    phantom = [p for p in REGISTRY if p not in SUPPORTED_PROTOCOLS]
    assert not phantom, f"registry lists protocols not in SUPPORTED_PROTOCOLS: {phantom}"


@pytest.mark.unit
@pytest.mark.parametrize("protocol", SUPPORTED_PROTOCOLS)
def test_where_hint_is_always_a_callable(protocol: str) -> None:
    """``where_hint`` has a fleet default (host:port), so it is never UNSUPPORTED."""
    cap = get_capabilities(protocol)
    assert cap is not None
    assert cap.where_hint is not UNSUPPORTED
    assert callable(cap.where_hint)


@pytest.mark.unit
@pytest.mark.parametrize("protocol", SUPPORTED_PROTOCOLS)
def test_each_capability_is_callable_or_explicitly_unsupported(protocol: str) -> None:
    """Each optional capability is EITHER a real callable OR the UNSUPPORTED sentinel.

    A bare ``None`` / missing value would silently mis-default — the exact bug
    class this registry exists to kill.
    """
    cap = get_capabilities(protocol)
    assert cap is not None
    for field in _SENTINEL_FIELDS:
        value = getattr(cap, field)
        assert value is UNSUPPORTED or callable(value), (
            f"protocol {protocol!r} capability {field!r} must be a callable or "
            f"UNSUPPORTED, got {value!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("protocol", SUPPORTED_PROTOCOLS)
def test_probe_style_is_valid(protocol: str) -> None:
    cap = get_capabilities(protocol)
    assert cap is not None
    assert cap.probe_style in _VALID_STYLES


@pytest.mark.unit
def test_informational_protocols_have_no_generic_doctor_probe() -> None:
    """PROBE_INFORMATIONAL protocols are reported via doctor's bespoke path, so the
    generic ``_probe`` must return "No probe implemented" for them (doctor_probe is
    UNSUPPORTED) — pinning the exact pre-refactor behavior."""
    for protocol, cap in REGISTRY.items():
        if cap.probe_style == PROBE_INFORMATIONAL:
            assert cap.doctor_probe is UNSUPPORTED, (
                f"{protocol!r} is informational but exposes a generic doctor_probe"
            )


@pytest.mark.unit
def test_doctor_informational_table_matches_registry() -> None:
    """The doctor's label+probe table for informational protocols must cover exactly
    the registry's PROBE_INFORMATIONAL set — no drift between the two."""
    from iaiops.doctor import _INFORMATIONAL_PROBES

    registry_informational = {
        p for p, c in REGISTRY.items() if c.probe_style == PROBE_INFORMATIONAL
    }
    assert set(_INFORMATIONAL_PROBES) == registry_informational


@pytest.mark.unit
def test_session_supported_set_is_stable() -> None:
    """The stateful-session protocol set (used in the teaching error message) is the
    exact set the pre-registry routing dict carried."""
    assert session_supported_protocols() == [
        "eip", "ethernetip", "fins", "iolink", "mc", "modbus",
        "mqtt", "opcua", "s7", "secsgem",
    ]
