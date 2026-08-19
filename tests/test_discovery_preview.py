"""The dry-run preview: it must be exhaustive, honest, and emit nothing.

The strongest test here is the last one — the preview is monkeypatched against a
socket module that raises on any use, so "emits nothing" is proven rather than
asserted in a docstring.
"""

from __future__ import annotations

import pytest

from iaiops.core.discovery import preview as pv
from iaiops.core.discovery.types import (
    L1_SWEEP,
    L2_IDENTIFY,
    Authorization,
    PacingPolicy,
    ScanPlan,
)

pytestmark = pytest.mark.unit


def plan(**kw) -> ScanPlan:
    base = {"cidrs": ("10.10.0.0/29",), "profile": "inventory"}
    return ScanPlan(**{**base, **kw})


class TestScopeExpansion:
    def test_network_and_broadcast_are_dropped_automatically(self):
        """A broadcast address is the one address a scan must never connect to."""
        scope = pv.expand_scope(plan(cidrs=("10.10.0.0/29",)))
        assert "10.10.0.0" not in scope.hosts
        assert "10.10.0.7" not in scope.hosts
        assert scope.host_count == 6
        assert set(scope.structural_exclusions) == {"10.10.0.0", "10.10.0.7"}

    def test_operator_exclusions_are_honoured_and_reported(self):
        scope = pv.expand_scope(plan(cidrs=("10.10.0.0/29",), excluded=("10.10.0.1", "10.10.0.2")))
        assert "10.10.0.1" not in scope.hosts
        assert scope.operator_exclusions == ("10.10.0.1", "10.10.0.2")
        assert scope.host_count == 4

    def test_a_cidr_exclusion_works(self):
        scope = pv.expand_scope(plan(cidrs=("10.10.0.0/28",), excluded=("10.10.0.8/29",)))
        assert not any(h.startswith("10.10.0.8") for h in scope.hosts)

    def test_explicit_hosts_are_included(self):
        scope = pv.expand_scope(plan(cidrs=(), hosts=("10.1.1.5", "10.1.1.6")))
        assert scope.hosts == ("10.1.1.5", "10.1.1.6")

    def test_duplicates_collapse_and_order_is_stable(self):
        scope = pv.expand_scope(plan(cidrs=(), hosts=("10.1.1.5", "10.1.1.5", "10.1.1.6")))
        assert scope.hosts == ("10.1.1.5", "10.1.1.6")

    def test_single_host_cidr_still_yields_the_host(self):
        scope = pv.expand_scope(plan(cidrs=("10.1.1.9/32",)))
        assert scope.hosts == ("10.1.1.9",)

    def test_an_implausible_prefix_is_refused_with_the_typo_explanation(self):
        with pytest.raises(pv.ScopeTooLarge, match="mistyped prefix"):
            pv.expand_scope(plan(cidrs=("10.0.0.0/8",)))

    def test_a_deliberate_large_scope_still_hits_the_host_cap(self):
        with pytest.raises(pv.ScopeTooLarge, match="cap for one"):
            pv.expand_scope(plan(cidrs=("10.0.0.0/8",), accept_large_scope=True))

    def test_the_cap_is_the_documented_one(self):
        with pytest.raises(pv.ScopeTooLarge):
            pv.expand_scope(plan(cidrs=("10.0.0.0/19",)))
        ok = pv.expand_scope(plan(cidrs=("10.0.0.0/21",)))
        assert ok.host_count <= pv.MAX_HOSTS_PER_SCAN

    def test_an_oversized_scope_is_refused_without_being_expanded(self):
        """A /8 holds 16.7M addresses. Materialising them just to discover they
        exceed the cap is slow on a laptop and an OOM on an edge box, so the
        refusal has to come from address arithmetic."""
        import time

        started = time.monotonic()
        with pytest.raises(pv.ScopeTooLarge, match="cap for one"):
            pv.expand_scope(plan(cidrs=("10.0.0.0/8",), accept_large_scope=True))
        assert time.monotonic() - started < 0.5

    def test_cidr_exclusions_count_toward_the_projection(self):
        """The cap is checked before expansion, so exclusions must be subtracted
        there too or a legitimately-narrowed large scope would be refused."""
        scope = pv.expand_scope(
            plan(cidrs=("10.0.0.0/20",), excluded=("10.0.0.0/21", "10.0.8.0/22", "10.0.12.0/22"))
        )
        assert scope.host_count == 0


class TestPortResolution:
    def test_default_profile_uses_only_the_default_ports(self):
        ports = {p.port for p in pv.resolve_ports(plan())}
        assert 502 in ports and 4840 in ports
        assert 1883 not in ports and 80 not in ports

    def test_a_protocol_hint_narrows(self):
        ports = {p.port for p in pv.resolve_ports(plan(protocols=("modbus",)))}
        assert ports == {502}

    def test_an_explicit_port_narrows(self):
        ports = {p.port for p in pv.resolve_ports(plan(ports=(502,)))}
        assert ports == {502}

    def test_a_port_off_the_allowlist_is_refused(self):
        with pytest.raises(ValueError, match="only narrow"):
            pv.resolve_ports(plan(ports=(23,)))

    def test_a_forbidden_port_is_refused_with_its_reason(self):
        with pytest.raises(ValueError, match="implicit I/O"):
            pv.resolve_ports(plan(ports=(2222,)))

    def test_a_protocol_hint_cannot_reach_past_the_profile(self):
        """A hint narrows; it never opts the run in to a port the profile left
        out. MTConnect's other homes are 80 and 8080 — ports the allowlist marks
        as ambiguous with IT — so a request to scan LESS must not start
        connecting to ordinary web servers on the OT VLAN."""
        with pytest.raises(ValueError, match="opt-in"):
            pv.resolve_ports(plan(protocols=("mtconnect",)))

    def test_an_explicit_opt_in_port_is_refused_under_a_default_profile(self):
        """Same rule for an explicit port, and it fails loudly rather than
        resolving to nothing: a silently empty port set is a scan that sweeps
        nothing while reporting that it swept."""
        with pytest.raises(ValueError, match="opt-in"):
            pv.resolve_ports(plan(ports=(1883,)))

    def test_deep_profile_includes_the_opt_in_ports(self):
        ports = {p.port for p in pv.resolve_ports(plan(profile="deep"))}
        assert 1883 in ports


class TestPreviewContent:
    def test_it_states_the_exact_connect_count(self):
        data = pv.plan_preview(plan())
        expected = data["scope"]["host_count"] * len(data["ports"])
        assert data["estimates"]["tcp_connects"] == expected

    def test_a_passive_plan_predicts_no_connects_and_no_emissions(self):
        data = pv.plan_preview(plan(profile="passive", stages=("L0_passive",)))
        assert data["emits_packets"] is False
        assert data["estimates"]["tcp_connects"] == 0
        assert data["stage_emissions"]["L0_passive"] == []

    def test_every_stage_declares_its_packet_classes(self):
        data = pv.plan_preview(plan(stages=(L1_SWEEP, L2_IDENTIFY)))
        assert data["stage_emissions"][L1_SWEEP] == ["tcp_connect"]
        assert "modbus_fc43" in data["stage_emissions"][L2_IDENTIFY]

    def test_declared_emissions_are_all_real_wire_classes(self):
        """The preview promises what the wire log later proves; the two vocabularies
        must be the same one."""
        from iaiops.core.discovery import wirelog

        for stage, kinds in pv.STAGE_EMISSIONS.items():
            for kind in kinds:
                assert kind in wirelog.KNOWN_KINDS, f"{stage} promises unknown {kind}"

    def test_the_will_not_do_list_is_present_and_leads_with_writes(self):
        data = pv.plan_preview(plan())
        assert data["will_not_do"]
        assert "No writes of any kind" in data["will_not_do"][0]

    def test_a_profile_needing_signoff_reports_unauthorized_when_missing(self):
        data = pv.plan_preview(plan(profile="standard"))
        assert data["authorization"]["required"] is True
        assert data["authorization"]["authorized"] is False

    def test_a_recorded_signoff_authorizes_it(self):
        data = pv.plan_preview(
            plan(profile="standard", authorization=Authorization(approved_by="zw", ticket="MOC-1"))
        )
        assert data["authorization"]["authorized"] is True

    def test_the_default_profile_needs_no_signoff(self):
        assert pv.plan_preview(plan())["authorization"]["authorized"] is True

    def test_forbidden_ports_are_shown_with_reasons(self):
        data = pv.plan_preview(plan())
        assert "2222" in data["forbidden_ports"]
        assert "secsgem" in data["never_identified"]

    def test_slow_pacing_produces_a_longer_worst_case(self):
        fast = pv.plan_preview(plan())["estimates"]["worst_case_s"]
        slow = pv.plan_preview(
            plan(
                profile="legacy-safe",
                pacing=PacingPolicy(
                    connects_per_second=5.0, max_concurrency=1, per_host_gap_ms=3000
                ),
            )
        )["estimates"]["worst_case_s"]
        assert slow > fast

    def test_text_rendering_is_signable(self):
        text = pv.preview_text(plan())
        assert "nothing has been sent to the network" in text
        assert "This scan will NOT:" in text
        assert "No writes of any kind" in text

    def test_text_flags_a_missing_signoff_loudly(self):
        assert "MISSING" in pv.preview_text(plan(profile="standard"))


class TestPreviewEmitsNothing:
    def test_the_preview_cannot_touch_the_network(self, monkeypatch):
        """The whole value of the preview is that it is derivable without touching
        anything. Proven by making every socket operation explode."""
        import socket

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("the preview touched the network")

        monkeypatch.setattr(socket, "socket", explode)
        monkeypatch.setattr(socket, "create_connection", explode)
        monkeypatch.setattr(socket, "getaddrinfo", explode)
        monkeypatch.setattr(socket, "gethostbyname", explode)

        data = pv.plan_preview(plan(profile="deep", cidrs=("10.10.0.0/28",)))
        assert data["scope"]["host_count"] == 14
        assert pv.preview_text(plan())
