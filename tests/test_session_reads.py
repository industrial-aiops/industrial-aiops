"""Every collectable protocol reads inside a held session.

Modbus got this first because it was the one measured: 3.7 TCP connections a
second, 1.8 million across a week-long run, against devices that commonly cap
connections in the single digits. Nothing about that is Modbus-specific — an
OPC-UA server with a session limit, an S7 CPU with a PG connection budget and a
Logix controller all have the same shape of ceiling.

Each of these is a thin read against an already-open client, and each is checked
for the same three things: it calls the client rather than opening anything, it
passes the reference through unchanged, and a protocol that lacks the capability
keeps working the old way rather than silently dropping out of collection.
"""

from __future__ import annotations

import pytest

from iaiops.core.collect.reader import session_read_for
from iaiops.core.runtime.capabilities import REGISTRY, UNSUPPORTED, get_capabilities

pytestmark = pytest.mark.unit

#: Protocols that can be sampled on a schedule at all.
COLLECTABLE = ("modbus", "opcua", "s7", "mc", "fins", "eip", "ethernetip")


class TestCoverage:
    @pytest.mark.parametrize("protocol", COLLECTABLE)
    def test_every_collectable_protocol_can_hold_a_session(self, protocol):
        """A protocol left out keeps reconnecting per sample — the exact churn
        this exists to remove, quietly retained for whichever line uses it."""
        assert session_read_for(protocol) is not None, f"{protocol} still reconnects per read"

    @pytest.mark.parametrize("protocol", COLLECTABLE)
    def test_it_also_has_something_to_open(self, protocol):
        """A session read with no session builder is unreachable."""
        cap = get_capabilities(protocol)
        assert cap.session_builder is not UNSUPPORTED

    def test_a_protocol_without_one_is_not_pretended_to_have_it(self):
        """BACnet, PROFINET and friends are stream- or broadcast-shaped."""
        assert session_read_for("bacnet") is None
        assert session_read_for("profinet") is None

    def test_no_protocol_claims_a_session_read_it_cannot_reach(self):
        for protocol, cap in REGISTRY.items():
            if cap.session_read is UNSUPPORTED:
                continue
            assert cap.session_builder is not UNSUPPORTED, (
                f"{protocol} declares a session read but nothing can open a session"
            )


class TestEachReadUsesTheOpenClient:
    def test_opcua_reads_the_node_from_the_client(self):
        from iaiops.core.runtime.capabilities import _session_read_opcua

        class Node:
            def read_data_value(self):
                # Shaped like a real DataValue rather than the minimum that
                # compiles: the session read reuses the connector's own
                # `_read_one`, which also reports datatype and status, and a
                # stub missing those would test a path the product does not run.
                variant = type(
                    "V", (), {"Value": 42, "VariantType": type("T", (), {"name": "Int32"})()}
                )()
                return type(
                    "DV",
                    (),
                    {
                        "Value": variant,
                        "SourceTimestamp": "2026-08-01T00:00:00",
                        "StatusCode": type("S", (), {"name": "Good"})(),
                    },
                )()

        seen = {}

        class Client:
            def get_node(self, nid):
                seen["node"] = nid
                return Node()

        value, _ts = _session_read_opcua(Client(), "ns=2;i=5")
        assert value == 42
        assert seen["node"] == "ns=2;i=5"

    def test_s7_reads_the_address_from_the_client(self):
        from iaiops.core.runtime.capabilities import _session_read_s7

        seen = {}

        class Client:
            def read(self, addrs):
                seen["addrs"] = addrs
                return [3.5]

        value, _ = _session_read_s7(Client(), "DB1,REAL4")
        assert value == 3.5
        assert seen["addrs"] == ["DB1,REAL4"]

    def test_mc_reads_the_device_from_the_client(self):
        from iaiops.core.runtime.capabilities import _session_read_mc

        seen = {}

        class Client:
            def batchread_wordunits(self, headdevice, readsize):
                seen.update(headdevice=headdevice, readsize=readsize)
                return [77]

        value, _ = _session_read_mc(Client(), "D100")
        assert value == 77
        assert seen == {"headdevice": "D100", "readsize": 1}

    def test_eip_reads_the_tag_from_the_client(self):
        from iaiops.core.runtime.capabilities import _session_read_eip

        seen = {}

        class Client:
            def read(self, tag):
                seen["tag"] = tag
                return type("R", (), {"Value": 9})()

        value, _ = _session_read_eip(Client(), "Line_Speed")
        assert value == 9
        assert seen["tag"] == "Line_Speed"

    def test_fins_reads_a_word_from_the_client(self):
        from iaiops.core.runtime.capabilities import _session_read_fins

        seen = {}

        class Client:
            def read_words(self, code, address, count):
                seen.update(code=code, address=address, count=count)
                return [1234]

        value, _ = _session_read_fins(Client(), "DM100")
        assert value == 1234
        assert seen["address"] == 100 and seen["count"] == 1

    def test_fins_reads_a_bit_through_the_bit_path(self):
        from iaiops.core.runtime.capabilities import _session_read_fins

        seen = {}

        class Client:
            def read_bits(self, code, address, bit, count):
                seen.update(address=address, bit=bit)
                return [True]

        value, _ = _session_read_fins(Client(), "CIO0.05")
        assert value is True
        assert seen == {"address": 0, "bit": 5}

    def test_fins_still_refuses_a_bare_reference_in_a_session(self):
        """The area-qualification rule cannot be lost by taking a second path
        into the same protocol — `DM100` and `CIO100` are different memory."""
        from iaiops.core.runtime.capabilities import _session_read_fins

        with pytest.raises(ValueError, match="(?i)area"):
            _session_read_fins(object(), "100")
