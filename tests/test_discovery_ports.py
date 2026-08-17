"""Guard tests for the scan allowlist, profiles, and pacing ceilings.

These are not coverage tests. Each one pins a safety property that this product
lives or dies by: a scan that faults a PLC once is finished in a conservative
OT market, so the rules must fail a build rather than rely on review catching a
plausible-looking change.
"""

from __future__ import annotations

import dataclasses

import pytest

from iaiops.core.discovery import ports as ports_mod
from iaiops.core.discovery import profiles as profiles_mod
from iaiops.core.discovery.types import (
    L0_PASSIVE,
    L2_IDENTIFY,
    L4_BROWSE,
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    STAGE_ORDER,
    Authorization,
    HostResult,
    PacingPolicy,
    PortResult,
    ScanPlan,
)

pytestmark = pytest.mark.unit


class TestAllowlistCannotGrowIntoForbiddenGround:
    def test_allowlist_and_never_scan_never_intersect(self):
        """The two tables are the whole safety argument; they must stay disjoint."""
        allow = {p.port for p in ports_mod.ALLOWLIST}
        overlap = allow & set(ports_mod.NEVER_SCAN)
        assert not overlap, (
            f"ports {sorted(overlap)} are both allowlisted and forbidden — "
            f"reasons for forbidding: { {k: ports_mod.NEVER_SCAN[k] for k in sorted(overlap)} }"
        )

    def test_no_port_offers_a_never_identified_protocol(self):
        offered = {proto for p in ports_mod.ALLOWLIST for proto in p.protocols}
        forbidden = offered & set(ports_mod.NEVER_IDENTIFIED)
        assert not forbidden, (
            f"{sorted(forbidden)} must never be identified by scanning: "
            f"{ {k: ports_mod.NEVER_IDENTIFIED[k] for k in sorted(forbidden)} }"
        )

    def test_secsgem_is_absent_everywhere(self):
        """An HSMS session can evict a fab tool's real MES host and stop it."""
        assert "secsgem" in ports_mod.NEVER_IDENTIFIED
        for entry in ports_mod.ALLOWLIST:
            assert "secsgem" not in entry.protocols

    def test_port_5000_is_mtconnect_http_only_and_opt_in(self):
        """5000 is shared with SECS-GEM HSMS. HTTP is refused harmlessly there;
        an HSMS session would not be. So the port stays, the protocol does not."""
        entry = ports_mod.describe_port(5000)
        assert entry is not None
        assert entry.protocols == ("mtconnect",)
        assert entry.default is False, "ambiguous with a production fab port — never default"

    def test_implicit_io_and_realtime_ports_are_forbidden(self):
        for port in (2222, 34962, 34963, 34964):
            assert port in ports_mod.NEVER_SCAN
            assert not ports_mod.is_allowlisted(port)


class TestSweepScope:
    def test_udp_ports_are_never_sweepable(self):
        """UDP has no handshake, and stray frames raise device error counters."""
        for entry in ports_mod.sweepable_ports(include_optional=True):
            assert entry.transport == ports_mod.TCP
        udp = [e.port for e in ports_mod.ALLOWLIST if e.transport == ports_mod.UDP]
        assert udp, "UDP entries should still be listed, for the report to explain"
        for port in udp:
            assert not ports_mod.is_allowlisted(port, ports_mod.UDP)

    def test_default_profile_ports_exclude_the_ambiguous_ones(self):
        default_ports = {e.port for e in ports_mod.sweepable_ports()}
        assert 502 in default_ports and 4840 in default_ports and 102 in default_ports
        for ambiguous in (80, 443, 8080, 1883, 8883, 5000):
            assert ambiguous not in default_ports

    def test_protocol_hint_can_only_narrow(self):
        narrowed = {e.port for e in ports_mod.ports_for_protocols(("modbus",))}
        every = {e.port for e in ports_mod.sweepable_ports(include_optional=True)}
        assert narrowed == {502}
        assert narrowed < every

    def test_protocol_hint_refuses_a_forbidden_protocol(self):
        with pytest.raises(ValueError, match="never discovered by scanning"):
            ports_mod.ports_for_protocols(("secsgem",))

    def test_unknown_protocol_hint_is_simply_empty_not_an_invented_port(self):
        assert ports_mod.ports_for_protocols(("nosuchproto",)) == ()

    def test_every_entry_documents_itself(self):
        """The note is the product: it's what a reviewer reads to trust this."""
        for entry in ports_mod.ALLOWLIST:
            assert entry.note.strip(), f"port {entry.port} has no rationale"


class TestPacingCeilingsAreNotConfiguration:
    def test_rate_ceiling_is_enforced(self):
        with pytest.raises(ValueError, match="not configurable"):
            PacingPolicy(connects_per_second=500.0)

    def test_concurrency_ceiling_is_enforced(self):
        with pytest.raises(ValueError, match="max_concurrency"):
            PacingPolicy(max_concurrency=64)

    def test_defaults_are_timid(self):
        p = PacingPolicy()
        assert p.connects_per_second <= 20.0
        assert p.max_concurrency <= 4
        assert p.per_host_gap_ms >= 250

    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_rate_refused(self, bad):
        with pytest.raises(ValueError):
            PacingPolicy(connects_per_second=bad)

    def test_ceilings_are_class_constants_not_overridable_fields(self):
        """A bare ``Final`` annotation still becomes a dataclass FIELD, which let a
        caller pass ``HARD_MAX_CPS=9999`` and lift their own ceiling — the exact
        bypass this class exists to prevent. Caught in review; pinned here."""
        names = {f.name for f in dataclasses.fields(PacingPolicy)}
        assert "HARD_MAX_CPS" not in names
        assert "HARD_MAX_CONCURRENCY" not in names
        with pytest.raises(TypeError):
            PacingPolicy(connects_per_second=500.0, HARD_MAX_CPS=9999.0)


class TestProfiles:
    def test_passive_profile_emits_nothing(self):
        prof = profiles_mod.get_profile("passive")
        assert prof.stages == (L0_PASSIVE,)
        plan = ScanPlan(stages=prof.stages)
        assert plan.emits_packets is False

    def test_default_profile_does_not_browse(self):
        prof = profiles_mod.get_profile(profiles_mod.DEFAULT_PROFILE)
        assert L4_BROWSE not in prof.stages

    def test_legacy_safe_does_not_even_identify(self):
        prof = profiles_mod.get_profile("legacy-safe")
        assert L2_IDENTIFY not in prof.stages
        assert prof.pacing.max_concurrency == 1
        assert prof.pacing.connects_per_second <= 5.0

    def test_deeper_profiles_require_authorization(self):
        assert "deep" in profiles_mod.REQUIRES_AUTHORIZATION
        assert "standard" in profiles_mod.REQUIRES_AUTHORIZATION
        assert "passive" not in profiles_mod.REQUIRES_AUTHORIZATION

    def test_every_profile_uses_known_stages_in_ladder_order(self):
        for prof in profiles_mod.PROFILES.values():
            assert all(s in STAGE_ORDER for s in prof.stages)
            ranks = [STAGE_ORDER.index(s) for s in prof.stages]
            assert ranks == sorted(ranks), f"{prof.name} stages are out of ladder order"

    def test_unknown_profile_teaches_the_options(self):
        with pytest.raises(ValueError, match="Available:"):
            profiles_mod.get_profile("aggressive")

    def test_menu_is_renderable(self):
        menu = profiles_mod.profile_menu()
        assert len(menu) == len(profiles_mod.PROFILES)
        assert all(row["summary"] for row in menu)


class TestResultHonesty:
    def test_refused_and_filtered_are_distinct_verdicts(self):
        """Collapsing these into 'closed' is where a scan report starts lying:
        refused proves the host is alive, filtered usually means an ACL."""
        assert PORT_REFUSED != PORT_FILTERED != PORT_OPEN

    def test_a_refused_port_still_proves_the_host_is_alive(self):
        host = HostResult(ip="10.0.0.5", ports=(PortResult(port=502, state=PORT_REFUSED),))
        assert host.alive is True

    def test_a_filtered_only_host_is_not_claimed_alive(self):
        host = HostResult(ip="10.0.0.6", ports=(PortResult(port=502, state=PORT_FILTERED),))
        assert host.alive is False

    def test_plan_rejects_unknown_stage(self):
        with pytest.raises(ValueError, match="unknown scan stages"):
            ScanPlan().with_stages(("L9_nuke",))

    def test_authorization_records_itself(self):
        assert Authorization().recorded is False
        assert Authorization(approved_by="zw", ticket="MOC-1").recorded is True
