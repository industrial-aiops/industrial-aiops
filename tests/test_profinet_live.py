"""Live PROFINET-DCP: the real `pnio-dcp` client against a station on a real wire.

PROFINET was the last **mock-only** protocol in this repo that was not hopeless.
The earlier note lumped it with EtherCAT ("no simulator exists, needs hardware"),
and that was wrong twice over: DCP Identify/Get/Set is request-response over
layer-2 Ethernet, and the missing half is a responder, not a device. A **veth
pair** gives two real interfaces on one host — `pnio-dcp` binds an `AF_PACKET`
socket on one end and `tests/profinet_dcp_station.py` answers on the other.

That makes this **rung 2b** (see `docs/VERIFICATION-RECORD.md`): a real wire, our
station, and a third-party client — `pnio-dcp`, which nobody here wrote — doing
the parsing. Rung 3 still needs a real ERTEC/Siemens station and always will.

Needs `CAP_NET_RAW` + `CAP_NET_ADMIN` (raw sockets, and creating the veth pair),
so it is gated on env vars supplied by the harness and SKIPS cleanly without them::

    sudo scripts/profinet_dcp_harness.sh

What is *not* covered: RT cyclic process data (out of scope by design), DCP
Blink / factory reset (also out of scope), a real device's timing, and every
vendor quirk a real station has.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# NOT importorskip: off Linux/Windows pnio-dcp raises NotImplementedError from its
# l2socket package rather than ImportError, which importorskip does not catch — so
# collection on macOS died instead of skipping.
try:
    import pnio_dcp  # noqa: F401
except Exception as exc:  # noqa: BLE001 — NotImplementedError on unsupported platforms
    pytest.skip(f"pnio-dcp unusable here: {exc}", allow_module_level=True)

# Bare module name, not ``tests.``: pytest puts this directory on sys.path, while
# the repo root is only there under ``python -m pytest``.
from profinet_dcp_station import DCPStation  # noqa: E402

from iaiops.connectors.profinet import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

pytestmark = [pytest.mark.integration]

CLIENT_IP = os.environ.get("IAIOPS_PROFINET_CLIENT_IP", "")
DEVICE_IF = os.environ.get("IAIOPS_PROFINET_DEVICE_IF", "")

needs_veth = pytest.mark.skipif(
    not (CLIENT_IP and DEVICE_IF),
    reason=(
        "live PROFINET-DCP needs a veth pair and raw sockets "
        "(IAIOPS_PROFINET_CLIENT_IP + IAIOPS_PROFINET_DEVICE_IF); "
        "run sudo scripts/profinet_dcp_harness.sh"
    ),
)

# pnio-dcp's IdentifyAll listens for the FULL timeout — it cannot know how many
# stations will answer — and the default is 7 seconds per call. That is a receive
# window, not a property of the protocol, so the tests shorten it. Everything else
# about the client, including the frames and the parsing, is untouched.
_IDENTIFY_WINDOW_S = 1.5


@pytest.fixture
def station() -> Any:
    """The virtual station, live on the peer end of the veth pair."""
    with DCPStation(DEVICE_IF) as running:
        yield running


@pytest.fixture
def target(monkeypatch: pytest.MonkeyPatch) -> TargetConfig:
    """A PROFINET endpoint bound to our end of the veth pair.

    The only patch is the identify window (see above): the builder still calls the
    real `_build_profinet_dcp`, so the DCP object, its raw socket and its frames
    are the library's.
    """
    from iaiops.core.runtime import connection

    real_builder = connection._build_profinet_dcp

    def _shorter_window(cfg: TargetConfig) -> Any:
        dcp = real_builder(cfg)
        dcp.identify_all_timeout = _IDENTIFY_WINDOW_S
        dcp.default_timeout = _IDENTIFY_WINDOW_S
        return dcp

    monkeypatch.setattr(connection, "_build_profinet_dcp", _shorter_window)
    return TargetConfig(name="pn-live", protocol="profinet", host=CLIENT_IP)


@needs_veth
def test_discover_finds_the_station_over_a_real_dcp_broadcast(station, target) -> None:
    """IdentifyAll on the wire, and the identity comes back off it.

    The MAC is the assertion that matters most: the connector never sends it, it
    is read off the Ethernet header of the station's reply — so a station that
    answered is the only way this passes.
    """
    result = ops.profinet_discover(target)

    assert result["station_count"] == 1, result
    found = result["stations"][0]
    assert found["name_of_station"] == station.name_of_station
    assert found["mac"] == station.mac
    assert found["ip"] == station.ip
    assert found["netmask"] == station.netmask
    assert found["gateway"] == station.gateway
    assert found["device_family"] == station.family
    assert (5, 0) in station.requests, (
        f"no DCP Identify request reached the station: {station.requests}"
    )


@needs_veth
def test_vendor_and_role_fields_are_empty_with_pnio_dcp(station, target) -> None:
    """The station SENDS DeviceID and DeviceRole; the client does not expose them.

    `pnio_dcp.Device` (1.2.0) carries name_of_station / MAC / IP / netmask /
    gateway / family and nothing else, so `vendor_id`, `device_id` and
    `device_roles` are always empty no matter what the station returned — which
    means `profinet_asset_inventory`'s `io_controller_count` is structurally zero.

    The mocked tests never showed this: their fake device had the attributes
    invented for it. Pinned here so it is a documented limit rather than a
    surprise, and so a future pnio-dcp that does expose them turns this red.
    """
    station.device_role = 0x02  # IO controller — sent on the wire, dropped by the client
    result = ops.profinet_discover(target)
    found = result["stations"][0]

    assert found["vendor_id"] is None, found
    assert found["device_id"] is None, found
    assert found["device_roles"] == [], found

    inventory = ops.profinet_asset_inventory(target)
    assert inventory["asset_count"] == 1
    assert inventory["io_controller_count"] == 0, (
        "a controller answered and was counted — pnio-dcp started exposing "
        "device_role, so the connector's role decoding is testable now"
    )


@needs_veth
def test_identify_by_name_matches_the_station_and_misses_cleanly(station, target) -> None:
    """A wrong name must return `found: False` — never the nearest station."""
    hit = ops.profinet_identify_station(target, station.name_of_station.upper())
    assert hit["found"] is True, hit
    assert hit["mac"] == station.mac

    miss = ops.profinet_identify_station(target, "no-such-station")
    assert miss["found"] is False, miss
    assert "name_of_station" in miss


@needs_veth
def test_station_params_takes_the_unicast_get_path(station, target) -> None:
    """`profinet_station_params` prefers a unicast DCP Get over a broadcast sweep.

    `station.requests` is the proof: a DCP Get (service 3) must appear. Without
    it the connector would have fallen back to filtering IdentifyAll, which
    returns the same answer for the wrong reason — the exact case a result-only
    assertion cannot tell apart.
    """
    result = ops.profinet_station_params(target, station.mac)

    assert result["found"] is True, result
    assert result["name_of_station"] == station.name_of_station
    assert result["ip"] == station.ip
    assert any(service == 3 for service, _type in station.requests), station.requests


@needs_veth
def test_dcp_set_dry_run_reads_the_before_state_and_writes_nothing(station, target) -> None:
    """The governed write's dry run must be a read on the wire, and only a read."""
    before_name = station.name_of_station
    result = ops.profinet_dcp_set(target, station.mac, set_name="renamed-by-dry-run")

    assert result["dry_run"] is True
    assert result["before"]["name_of_station"] == before_name
    assert result["would_set"]["name_of_station"] == "renamed-by-dry-run"
    assert station.name_of_station == before_name, "a dry run changed the station"
    assert all(service != 4 for service, _type in station.requests), (
        f"a DCP Set went on the wire during a dry run: {station.requests}"
    )


@needs_veth
def test_dcp_set_renames_the_station_and_the_before_state_reverses_it(station, target) -> None:
    """The one write this connector has, applied and then undone on a real wire.

    Re-addressing a live station is the OT-dangerous operation the governance
    harness exists for; `before` is what makes it reversible. Asserting the
    rename against the station's own state — then putting it back and reading
    that back too — is the only way to know `before` is a usable undo and not a
    plausible-looking dict.
    """
    original = station.name_of_station

    applied = ops.profinet_dcp_set(target, station.mac, set_name="iaiops-renamed", dry_run=False)
    assert applied["applied"] is True, applied
    assert applied["before"]["name_of_station"] == original
    assert station.name_of_station == "iaiops-renamed", "the Set never reached the station"

    # The station now answers under the new name.
    assert ops.profinet_identify_station(target, "iaiops-renamed")["found"] is True

    restored = ops.profinet_dcp_set(
        target, station.mac, set_name=applied["before"]["name_of_station"], dry_run=False
    )
    assert restored["applied"] is True
    assert station.name_of_station == original, "the captured BEFORE did not restore"
