"""L0 passive — the stage whose entire claim is that it emits nothing.

The claim is only as good as two details, and both are pinned here:

* the BSD/macOS path must pass ``-n``, because ``arp -a`` reverse-resolves every
  address and puts a DNS query on the network per entry;
* an unreadable cache must produce a NOTE, never a silent empty table — "nothing
  is on this network" and "I could not look" are different answers.

The fixture text below is copied verbatim from two real kernels (Ubuntu 24.04
``/proc/net/arp`` and macOS ``arp -an``), including the same NIC printed as
``48:21:0b:33:57:94`` by one and ``48:21:b:33:57:94`` by the other — the reason
normalization exists at all.
"""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from iaiops.core.discovery.passive import (
    ARPEntry,
    merge_passive,
    normalize_mac,
    passive_hosts,
    read_arp_table,
)
from iaiops.core.discovery.types import PORT_OPEN, HostResult, PortResult

pytestmark = pytest.mark.unit

# Verbatim from Ubuntu 24.04. The last row is deliberately incomplete (flags 0x0):
# an ARP request that was never answered.
PROC_ARP_TEXT = """IP address       HW type     Flags       HW address            Mask     Device
192.168.60.1     0x1         0x2         f0:8e:db:19:1c:78     *        ens34
192.168.60.15    0x1         0x2         48:21:0b:33:57:94     *        ens34
192.168.60.96    0x1         0x2         6a:4e:10:54:dc:fb     *        ens34
192.168.60.240   0x1         0x0         00:00:00:00:00:00     *        ens34
"""

# Verbatim from macOS. Note the unpadded octets and the '(incomplete)' row.
BSD_ARP_TEXT = """? (169.254.169.254) at (incomplete) on en0 [ethernet]
? (192.168.60.1) at f0:8e:db:19:1c:78 on en0 ifscope [ethernet]
? (192.168.60.15) at 48:21:b:33:57:94 on en0 ifscope [ethernet]
? (192.168.60.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]
"""

WINDOWS_ARP_TEXT = """
Interface: 192.168.60.20 --- 0xa
  Internet Address      Physical Address      Type
  192.168.60.1          f0-8e-db-19-1c-78     dynamic
  192.168.60.15         48-21-0B-33-57-94     dynamic
  192.168.60.255        ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""


class TestMacNormalization:
    def test_macos_short_octets_become_the_linux_form(self):
        """The same NIC, printed by two kernels. Left alone it becomes two
        assets the moment a survey is run from a different laptop."""
        assert normalize_mac("48:21:b:33:57:94") == "48:21:0b:33:57:94"

    def test_windows_hyphens_and_case_are_normalized(self):
        assert normalize_mac("48-21-0B-33-57-94") == "48:21:0b:33:57:94"

    def test_incomplete_is_not_a_mac(self):
        assert normalize_mac("(incomplete)") == ""

    def test_broadcast_is_not_a_device(self):
        """Every ARP cache holds the subnet broadcast. Listing it puts
        192.168.60.255 in an inventory as though it were in a cabinet."""
        assert normalize_mac("ff:ff:ff:ff:ff:ff") == ""

    def test_multicast_is_not_a_device(self):
        assert normalize_mac("01:00:5e:00:00:16") == ""
        assert normalize_mac("33:33:00:00:00:01") == ""

    def test_all_zero_is_not_a_device(self):
        assert normalize_mac("00:00:00:00:00:00") == ""

    def test_garbage_is_rejected_rather_than_guessed(self):
        for bad in ("", "not-a-mac", "48:21:0b:33:57", "48:21:0b:33:57:94:aa", "zz:21:0b:33:57:94"):
            assert normalize_mac(bad) == "", bad


class TestLinuxParsing:
    def test_real_proc_arp_is_parsed(self, tmp_path: Path):
        path = tmp_path / "arp"
        path.write_text(PROC_ARP_TEXT)
        entries, notes = read_arp_table(system="Linux", proc_arp=path)
        assert notes == ()
        assert [e.ip for e in entries] == ["192.168.60.1", "192.168.60.15", "192.168.60.96"]
        assert entries[0].interface == "ens34"

    def test_an_incomplete_entry_is_not_a_host(self, tmp_path: Path):
        """Flags 0x0 means the request went unanswered — the opposite of
        evidence that something is there."""
        path = tmp_path / "arp"
        path.write_text(PROC_ARP_TEXT)
        entries, _ = read_arp_table(system="Linux", proc_arp=path)
        assert "192.168.60.240" not in {e.ip for e in entries}

    def test_an_unreadable_cache_is_a_note_not_an_empty_network(self, tmp_path: Path):
        entries, notes = read_arp_table(system="Linux", proc_arp=tmp_path / "nope")
        assert entries == ()
        assert notes and "could not read" in notes[0]


class TestBSDParsing:
    def test_real_arp_output_is_parsed(self):
        entries, notes = read_arp_table(system="Darwin", runner=lambda argv: BSD_ARP_TEXT)
        assert notes == ()
        assert {e.ip for e in entries} == {"192.168.60.1", "192.168.60.15"}

    def test_the_numeric_flag_is_always_passed(self):
        """``arp -a`` reverse-resolves every address, emitting a DNS query per
        entry. That would make the one profile whose entire promise is 'emits
        nothing' emit something."""
        seen: list[list[str]] = []

        def runner(argv):
            seen.append(argv)
            return BSD_ARP_TEXT

        read_arp_table(system="Darwin", runner=runner)
        assert seen, "the arp command was never invoked"
        for argv in seen:
            assert "-an" in argv or "-n" in argv, f"{argv} would resolve names over the network"

    def test_it_falls_back_to_the_bare_command_name(self):
        calls: list[list[str]] = []

        def runner(argv):
            calls.append(argv)
            return "" if argv[0].startswith("/") else BSD_ARP_TEXT

        entries, notes = read_arp_table(system="Darwin", runner=runner)
        assert len(calls) == 2
        assert entries and notes == ()

    def test_no_output_at_all_is_reported(self):
        entries, notes = read_arp_table(system="Darwin", runner=lambda argv: "")
        assert entries == ()
        assert notes and "could not be read" in notes[0]


class TestWindowsParsing:
    def test_real_arp_output_is_parsed(self):
        entries, _ = read_arp_table(system="Windows", runner=lambda argv: WINDOWS_ARP_TEXT)
        assert {e.ip for e in entries} == {"192.168.60.1", "192.168.60.15"}

    def test_the_interface_header_line_is_not_mistaken_for_a_host(self):
        entries, _ = read_arp_table(system="Windows", runner=lambda argv: WINDOWS_ARP_TEXT)
        assert "192.168.60.20" not in {e.ip for e in entries}


class TestUnsupportedPlatform:
    def test_a_gap_in_this_tool_is_not_reported_as_an_empty_network(self):
        entries, notes = read_arp_table(system="Plan9")
        assert entries == ()
        assert notes and "NOT a statement that the network is empty" in notes[0]


class TestHostsAndMerge:
    def test_a_cached_host_is_alive_on_its_mac_alone(self):
        hosts = passive_hosts((ARPEntry("10.0.0.5", "00:0c:29:45:3b:d8", "en0"),))
        assert hosts[0].alive is True
        assert hosts[0].sources == ("arp",)
        assert hosts[0].ports == ()

    def test_scope_narrows_the_cache_to_what_was_authorized(self):
        """The cache holds everything this machine ever spoke to, including
        addresses outside the scan the operator signed off on."""
        entries = (
            ARPEntry("10.0.0.5", "00:0c:29:45:3b:d8"),
            ARPEntry("192.168.1.9", "00:0c:29:45:3b:d9"),
        )
        hosts = passive_hosts(entries, scope=("10.0.0.5",))
        assert [h.ip for h in hosts] == ["10.0.0.5"]

    def test_merge_keeps_both_provenances(self):
        """'The ARP cache knew it AND it answered a connect' is a stronger
        statement than either alone, and the report says which."""
        swept = (HostResult(ip="10.0.0.5", sources=("tcp",), ports=(PortResult(502, PORT_OPEN),)),)
        cached = passive_hosts((ARPEntry("10.0.0.5", "00:0c:29:45:3b:d8"),))
        merged = merge_passive(swept, cached)
        assert len(merged) == 1
        assert merged[0].sources == ("arp", "tcp")
        assert merged[0].mac == "00:0c:29:45:3b:d8"
        assert merged[0].ports == swept[0].ports

    def test_a_host_only_the_cache_knew_is_not_dropped(self):
        """It answered an ARP request. It exists, even though it refused or
        never answered every port we are allowed to try."""
        cached = passive_hosts((ARPEntry("10.0.0.9", "00:0c:29:45:3b:d9"),))
        merged = merge_passive((), cached)
        assert [h.ip for h in merged] == ["10.0.0.9"]

    def test_merge_does_not_duplicate_a_source(self):
        swept = (HostResult(ip="10.0.0.5", sources=("arp",)),)
        cached = passive_hosts((ARPEntry("10.0.0.5", "00:0c:29:45:3b:d8"),))
        assert merge_passive(swept, cached)[0].sources == ("arp",)


@pytest.mark.integration
class TestAgainstThisMachinesRealKernel:
    """Reads the actual cache. The fixtures above came from two real kernels,
    but a fixture cannot catch the day a kernel changes its output format."""

    def test_the_local_cache_parses_without_notes(self):
        if platform.system() not in ("Linux", "Darwin", "Windows"):
            pytest.skip(f"no ARP reader for {platform.system()}")
        entries, notes = read_arp_table()
        assert notes == (), f"the real cache produced notes: {notes}"
        for entry in entries:
            assert normalize_mac(entry.mac) == entry.mac, "entries must be pre-normalized"
            assert entry.ip.count(".") == 3

    def test_no_broadcast_or_multicast_survives_a_real_read(self):
        if platform.system() not in ("Linux", "Darwin", "Windows"):
            pytest.skip(f"no ARP reader for {platform.system()}")
        entries, _ = read_arp_table()
        for entry in entries:
            first = int(entry.mac.split(":")[0], 16)
            assert not first & 0x01, f"{entry.ip} -> {entry.mac} is not a unicast device"
