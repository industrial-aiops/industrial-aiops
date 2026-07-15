"""CC-Link master-PLC route tests (docs/CCLINK.md) against a mocked pymcprotocol client.

Same double pattern as ``test_mc.py``: ``connection._build_mc_client`` is monkeypatched,
exercising the template catalog, refresh-image reads (with per-project overrides), and
the SB/SW network-health decode for both classic CC-Link and CC-Link IE Field — no PLC.
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.connectors.mc import cclink, ops
from iaiops.core.runtime.config import TargetConfig


class _FakeMasterPLC:
    """MC client double for a CC-Link master: link images + SB/SW diagnostics."""

    def __init__(self):
        # Station 2 in data-link error (bit 1 of the first status word), station 5
        # baton-pass lost (bit 4 of the first baton word). SB0049 own-station OK.
        self.words = {
            "SW0080": [0b0000_0000_0000_0010, 0, 0, 0],
            "SW00B0": [0b0000_0000_0000_0010, 0, 0, 0, 0, 0, 0, 0],
            "SW00A0": [0b0000_0000_0001_0000, 0, 0, 0, 0, 0, 0, 0],
            "W0": [11, 22, 33, 44] + [0] * 60,
            "W100": [55, 66] + [0] * 62,
            "W1000": [77] + [0] * 63,
        }
        self.bits = {"SB0049": [0], "X1000": [1, 0, 1], "Y1000": [0, 1], "B0": [1], "B1000": [0]}
        self.requests: list[tuple[str, str, int]] = []

    def connect(self, ip, port):
        pass

    def close(self):
        pass

    def batchread_wordunits(self, headdevice, readsize):
        self.requests.append(("word", headdevice, readsize))
        base = self.words.get(headdevice, [0])
        return (base + [0] * readsize)[:readsize]

    def batchread_bitunits(self, headdevice, readsize):
        self.requests.append(("bit", headdevice, readsize))
        base = self.bits.get(headdevice, [0])
        return (base + [0] * readsize)[:readsize]


@pytest.fixture
def master(monkeypatch):
    client = _FakeMasterPLC()
    monkeypatch.setattr(conn, "_build_mc_client", lambda target: client)
    target = TargetConfig(name="line1_master", protocol="mc", host="10.0.0.9", plctype="Q")
    return target, client


class TestTemplates:
    def test_catalog_lists_both_networks(self):
        listed = ops.mc_cclink_templates()["templates"]
        assert {t["network"] for t in listed} == {"cclink", "cclink_ie_field"}
        # Honesty discipline: refresh assignment is per-project — every template must say so.
        assert all("待核实" in t["caveat"] for t in listed)

    def test_unknown_template_names_the_known_ones(self):
        with pytest.raises(KeyError, match="cclink_classic_default"):
            cclink.get_link_template("nope")

    def test_resolve_area_is_immutable_and_bounded(self):
        area = cclink.get_link_template("cclink_classic_default").areas[0]
        resolved = cclink.resolve_area(area, "X1200:9999")
        assert (resolved.device, resolved.count) == ("X1200", 1024)
        assert (area.device, area.count) == ("X1000", 128)  # original untouched

    def test_resolve_area_rejects_bad_count(self):
        area = cclink.get_link_template("cclink_classic_default").areas[0]
        with pytest.raises(ValueError, match="HEAD"):
            cclink.resolve_area(area, "X1200:lots")


class TestLinkRead:
    def test_reads_all_areas_of_the_template(self, master):
        target, client = master
        out = ops.mc_cclink_link_read(target, "cclink_ie_field_default")
        assert [a["area"] for a in out["areas"]] == ["rx", "ry", "rwr", "rww"]
        rwr = next(a for a in out["areas"] if a["area"] == "rwr")
        assert (rwr["device"], rwr["values"][0]) == ("W0", 11)
        rx = next(a for a in out["areas"] if a["area"] == "rx")
        assert rx["values"][0] is True
        assert "待核实" in out["caveat"]

    def test_override_remaps_head_device_and_count(self, master):
        target, client = master
        out = ops.mc_cclink_link_read(target, "cclink_classic_default", overrides={"rwr": "W100:2"})
        rwr = next(a for a in out["areas"] if a["area"] == "rwr")
        assert (rwr["device"], rwr["count"], rwr["values"]) == ("W100", 2, [55, 66])

    def test_unknown_override_area_is_rejected(self, master):
        target, _ = master
        with pytest.raises(ValueError, match="Unknown override"):
            ops.mc_cclink_link_read(target, "cclink_classic_default", overrides={"zz": "W0"})


class TestNetworkHealth:
    def test_ie_field_decodes_error_and_baton_stations(self, master):
        target, client = master
        out = ops.mc_cclink_network_health(target, network="cclink_ie_field", stations=16)
        assert out["stations_in_error"] == [2]
        assert out["baton_pass_lost"] == [5]
        assert out["own_station_error"] is False
        assert out["healthy"] is False
        assert out["registers"]["stations_status"] == "SW00B0"
        # exactly one status word needed for 16 stations
        assert ("word", "SW00B0", 1) in client.requests

    def test_classic_uses_sw0080_and_has_no_own_bit(self, master):
        target, client = master
        out = ops.mc_cclink_network_health(target, network="cclink", stations=32)
        assert out["stations_in_error"] == [2]
        assert out["own_station_error"] is None
        assert out["baton_pass_lost"] == []
        assert ("word", "SW0080", 2) in client.requests
        assert not any(dev == "SB0049" for _, dev, _ in client.requests)

    def test_all_clear_reports_healthy(self, master):
        target, client = master
        client.words["SW00B0"] = [0] * 8
        client.words["SW00A0"] = [0] * 8
        out = ops.mc_cclink_network_health(target, network="cclink_ie_field", stations=32)
        assert out["healthy"] is True
        assert out["stations_in_error"] == []

    def test_stations_clamped_to_network_maximum(self, master):
        target, _ = master
        out = ops.mc_cclink_network_health(target, network="cclink", stations=500)
        assert out["stations_checked"] == 64

    def test_unknown_network_is_rejected(self, master):
        target, _ = master
        with pytest.raises(KeyError, match="cclink_ie_field"):
            ops.mc_cclink_network_health(target, network="profibus")


class TestBitmapDecode:
    def test_station_bit_addressing_across_words(self):
        # Station 17 = bit 0 of the SECOND word.
        rows = cclink.decode_station_bitmap([0, 1], 17)
        assert rows[16] == {"station": 17, "ok": False}
        assert all(r["ok"] for r in rows[:16])
