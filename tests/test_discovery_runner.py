"""The scan runner — where the result can quietly become less honest than the run.

Each stage is already careful on its own. What this level adds is the chance to
lose that: to skip a stage the operator authorised, to return an empty list
instead of a diagnosis, or to summarise the wire from what succeeded rather than
from what was sent. Those three are the tests below.
"""

from __future__ import annotations

import errno

import pytest

from iaiops.core.discovery import identify, wirelog
from iaiops.core.discovery.passive import ARPEntry
from iaiops.core.discovery.runner import NOT_IMPLEMENTED, AuthorizationRequired, run_scan
from iaiops.core.discovery.types import (
    L0_BROADCAST,
    L0_PASSIVE,
    L1_SWEEP,
    L2_IDENTIFY,
    L4_BROWSE,
    VERDICT_NO_DEVICES,
    VERDICT_OK,
    VERDICT_PARTIAL,
    Authorization,
    PacingPolicy,
    ScanPlan,
)
from iaiops.core.runtime.session_factory import OTConnectionError

pytestmark = pytest.mark.unit

BRISK = PacingPolicy(
    connects_per_second=100.0,
    max_concurrency=8,
    per_host_gap_ms=0,
    identify_gap_ms=0,
    host_backoff_after=99,
    segment_abort_after=9999,
)


class FakeSocket:
    def shutdown(self, how):  # noqa: D102
        pass

    def close(self):  # noqa: D102
        pass


def connector_for(open_ports: dict[str, set[int]], refusing: set[str] = frozenset()):
    """A socket factory: named hosts open named ports, some refuse, rest time out."""

    def connect(address, timeout):
        host, port = address
        if port in open_ports.get(host, ()):
            return FakeSocket()
        if host in refusing or host in open_ports:
            raise OSError(errno.ECONNREFUSED, "refused")
        raise TimeoutError()

    return connect


def fake_identify(protocol: str, outcome):
    def run(ip, port, timeout_s, log):
        log.record(wirelog.MODBUS_FC43, host=ip, detail=str(port))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return {
        protocol: identify.IdentifyProbe(
            protocol=protocol, wire_kind=wirelog.MODBUS_FC43, rationale="test", run=run
        )
    }


def plan_for(hosts: tuple[str, ...], **kwargs) -> ScanPlan:
    defaults = {"site": "test", "hosts": hosts, "profile": "inventory", "pacing": BRISK}
    return ScanPlan(**{**defaults, **kwargs})


NO_ARP = lambda: ((), ())  # noqa: E731
CLOCK = lambda: "2026-08-18T00:00:00+00:00"  # noqa: E731


class TestAuthorization:
    def test_a_profile_that_needs_signoff_refuses_without_one(self):
        """Enforced in the library, not the CLI, so calling run_scan directly
        cannot route around it."""
        plan = plan_for(("10.0.0.5",), profile="standard")
        with pytest.raises(AuthorizationRequired, match="recorded authorization"):
            run_scan(plan, connector=connector_for({}), arp_reader=NO_ARP)

    def test_it_refuses_before_emitting_anything(self):
        log = wirelog.WireLog()
        plan = plan_for(("10.0.0.5",), profile="standard")
        with pytest.raises(AuthorizationRequired):
            run_scan(plan, log=log, connector=connector_for({}), arp_reader=NO_ARP)
        assert log.total() == 0, "packets were sent before the authorization check"

    def test_a_recorded_signoff_lets_it_run(self):
        plan = plan_for(
            ("10.0.0.5",),
            profile="standard",
            authorization=Authorization(approved_by="J. Controls", ticket="CHG-91"),
        )
        result = run_scan(plan, connector=connector_for({}), arp_reader=NO_ARP)
        assert result.plan.authorization.approved_by == "J. Controls"

    def test_the_default_profile_needs_no_signoff(self):
        """The everyday case must not require paperwork, or nobody runs it."""
        result = run_scan(plan_for(("10.0.0.5",)), connector=connector_for({}), arp_reader=NO_ARP)
        assert result.verdict in (VERDICT_NO_DEVICES, VERDICT_PARTIAL)


class TestUnimplementedStagesAreNamed:
    def test_a_requested_but_unbuilt_stage_is_reported(self):
        """Running four stages when six were authorised, without saying so, is how
        a report comes to claim coverage it does not have."""
        plan = plan_for(
            ("10.0.0.5",),
            stages=(L0_PASSIVE, L0_BROADCAST, L1_SWEEP, L2_IDENTIFY, L4_BROWSE),
        )
        result = run_scan(plan, connector=connector_for({}), arp_reader=NO_ARP)
        assert any(L0_BROADCAST in note for note in result.notes)
        assert any(L4_BROWSE in note for note in result.notes)

    def test_stages_that_are_built_are_not_flagged(self):
        result = run_scan(plan_for(("10.0.0.5",)), connector=connector_for({}), arp_reader=NO_ARP)
        assert not any(L1_SWEEP in note for note in result.notes)

    def test_every_declared_gap_names_the_stage_and_the_reason(self):
        for stage, reason in NOT_IMPLEMENTED.items():
            assert stage
            assert len(reason) > 40, f"{stage}'s reason is too thin to act on"


class TestVerdicts:
    def test_a_confirmed_protocol_is_ok(self):
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({"10.0.0.3": {502}}),
            arp_reader=NO_ARP,
            identify_plan=fake_identify("modbus", {"vendor": "Schneider"}),
        )
        assert result.verdict == VERDICT_OK
        assert result.devices[0].identity["modbus"]["vendor"] == "Schneider"

    def test_hosts_that_are_there_but_speak_nothing_are_partial_not_empty(self):
        """A very common answer on an IT segment, and completely different from
        finding nothing at all."""
        result = run_scan(
            plan_for(("10.0.0.5",)),
            connector=connector_for({}, refusing={"10.0.0.5"}),
            arp_reader=NO_ARP,
        )
        assert result.verdict == VERDICT_PARTIAL
        assert result.hosts[0].alive is True

    def test_total_silence_is_no_devices_found(self):
        result = run_scan(plan_for(("10.0.0.9",)), connector=connector_for({}), arp_reader=NO_ARP)
        assert result.verdict == VERDICT_NO_DEVICES

    def test_an_open_port_nothing_confirmed_is_partial(self):
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({"10.0.0.3": {502}}),
            arp_reader=NO_ARP,
            identify_plan=fake_identify("modbus", OTConnectionError("reset")),
        )
        assert result.verdict == VERDICT_PARTIAL


class TestAnEmptyResultExplainsItself:
    def test_silence_is_diagnosed_never_returned_bare(self):
        result = run_scan(plan_for(("10.0.0.9",)), connector=connector_for({}), arp_reader=NO_ARP)
        assert result.notes, "a scan that found nothing returned no explanation"
        assert any("firewall" in n or "VLAN" in n for n in result.notes)

    def test_alive_but_silent_hosts_get_a_different_diagnosis(self):
        """Refused and filtered are never merged, and neither are their notes."""
        result = run_scan(
            plan_for(("10.0.0.5",)),
            connector=connector_for({}, refusing={"10.0.0.5"}),
            arp_reader=NO_ARP,
        )
        assert any("ALIVE" in n and "not a failure" in n for n in result.notes)


class TestPassiveIsFoldedIn:
    def test_a_host_only_the_arp_cache_knew_still_appears(self):
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({}),
            arp_reader=lambda: ((ARPEntry("10.0.0.3", "00:0c:29:45:3b:d8", "en0"),), ()),
        )
        assert result.hosts[0].mac == "00:0c:29:45:3b:d8"
        assert "arp" in result.hosts[0].sources

    def test_arp_notes_reach_the_result(self):
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({}),
            arp_reader=lambda: ((), ("could not read /proc/net/arp: denied",)),
        )
        assert any("could not read" in n for n in result.notes)

    def test_the_passive_profile_emits_nothing_at_all(self):
        """The one profile whose entire promise is silence."""
        log = wirelog.WireLog()
        plan = plan_for(("10.0.0.3",), profile="passive", stages=(L0_PASSIVE,))
        result = run_scan(
            plan,
            log=log,
            connector=connector_for({"10.0.0.3": {502}}),
            arp_reader=lambda: ((ARPEntry("10.0.0.3", "00:0c:29:45:3b:d8"),), ()),
        )
        assert log.total() == 0, f"the passive profile emitted {log.summary()}"
        assert result.hosts[0].ip == "10.0.0.3"

    def test_the_cache_is_narrowed_to_the_authorized_scope(self):
        """The cache holds every host this machine ever spoke to, including ones
        outside the scan that was signed off."""
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({}),
            arp_reader=lambda: (
                (
                    ARPEntry("10.0.0.3", "00:0c:29:45:3b:d8"),
                    ARPEntry("192.168.1.9", "00:0c:29:01:02:03"),
                ),
                (),
            ),
        )
        assert {h.ip for h in result.hosts} == {"10.0.0.3"}


class TestTheWireSummaryIsWhatWasSent:
    def test_failed_probes_are_counted_too(self):
        """A trust page that counted only successful requests would understate
        exactly the traffic an operator is worried about."""
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({"10.0.0.3": {502}}),
            arp_reader=NO_ARP,
            identify_plan=fake_identify("modbus", OTConnectionError("reset")),
        )
        assert result.wire_summary[wirelog.MODBUS_FC43] == 1
        assert result.wire_summary[wirelog.TCP_CONNECT] >= 1

    def test_only_declared_packet_classes_appear(self):
        result = run_scan(
            plan_for(("10.0.0.3",)),
            connector=connector_for({"10.0.0.3": {502}}),
            arp_reader=NO_ARP,
            identify_plan=fake_identify("modbus", {"vendor": "x"}),
        )
        assert set(result.wire_summary) <= set(wirelog.KNOWN_KINDS)


class TestResultShape:
    def test_hosts_are_sorted_numerically_not_lexically(self):
        """10.0.0.9 before 10.0.0.10 — the report is read by a person."""
        hosts = ("10.0.0.10", "10.0.0.9", "10.0.0.2")
        result = run_scan(
            plan_for(hosts), connector=connector_for({}, refusing=set(hosts)), arp_reader=NO_ARP
        )
        assert [h.ip for h in result.hosts] == ["10.0.0.2", "10.0.0.9", "10.0.0.10"]

    def test_the_plan_and_timestamps_ride_with_the_result(self):
        plan = plan_for(("10.0.0.5",))
        result = run_scan(plan, connector=connector_for({}), arp_reader=NO_ARP, clock=CLOCK)
        assert result.plan is plan
        assert result.started_at == CLOCK() and result.finished_at == CLOCK()

    def test_notes_are_deduplicated(self):
        result = run_scan(
            plan_for(("10.0.0.1", "10.0.0.2")), connector=connector_for({}), arp_reader=NO_ARP
        )
        assert len(result.notes) == len(set(result.notes))


class TestBackoffIsVisiblePerHost:
    def test_a_dropped_host_says_its_row_is_incomplete(self):
        """Its row has fewer ports than its neighbours'. Without the per-host
        note that reads as an inconsistent scan rather than a careful one."""
        pacing = PacingPolicy(
            connects_per_second=100.0,
            max_concurrency=1,
            per_host_gap_ms=0,
            identify_gap_ms=0,
            host_backoff_after=1,
            segment_abort_after=9999,
        )
        result = run_scan(
            plan_for(("10.0.0.9",), pacing=pacing),
            connector=connector_for({}),
            arp_reader=NO_ARP,
        )
        assert any("incomplete by design" in e for e in result.hosts[0].errors)


class TestAbortIsStructural:
    """The abort verdict must not depend on the wording of an exception message.
    Rewording pacing.py would otherwise make an aborted, possibly
    plant-disturbing scan report itself as ok."""

    def test_sweep_reports_the_abort_as_a_flag(self):
        from iaiops.core.discovery.sweep import sweep_hosts
        from iaiops.core.discovery.types import PacingPolicy

        def always_timeout(address, timeout=None):
            raise TimeoutError

        pacing = PacingPolicy(connects_per_second=100.0, per_host_gap_ms=0, segment_abort_after=2)
        _hosts, _notes, aborted = sweep_hosts(
            [f"10.0.0.{i}" for i in range(1, 20)],
            [502],
            pacing=pacing,
            connector=always_timeout,
        )
        assert aborted is True, "an unhealthy segment must be signalled structurally"

    def test_a_healthy_sweep_is_not_flagged_as_aborted(self):
        from iaiops.core.discovery.sweep import sweep_hosts
        from iaiops.core.discovery.types import PacingPolicy

        def refuse(address, timeout=None):
            raise ConnectionRefusedError(111, "refused")

        _hosts, _notes, aborted = sweep_hosts(
            ["10.0.0.1"], [502], pacing=PacingPolicy(per_host_gap_ms=0), connector=refuse
        )
        assert aborted is False
