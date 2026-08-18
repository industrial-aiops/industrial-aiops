"""L2 identification — the stage that decides whether this product gets banned.

Three groups of properties are pinned here, and they are not equally interesting:

* **The table's structural invariants.** ``secsgem`` must be absent, every port
  in the allowlist must be *accounted for* (probe or documented refusal), and
  every emission must be pre-declared. These are asserted against the real
  tables, not fixtures, so they fail on the edit that breaks them.
* **Outcome mapping.** A device that answers in-protocol and refuses is
  CONFIRMED; a device that never answered is ``port_only`` with no vendor.
  Getting this backwards produces an inventory full of invented rows, which is
  the failure that loses a customer quietly.
* **What is never touched.** Refused and filtered ports are not probed, and a
  host with nothing open emits nothing at all.
"""

from __future__ import annotations

import pytest

from iaiops.core.discovery import identify, ports, preview, wirelog
from iaiops.core.discovery.identify import (
    IDENTIFY_PLAN,
    NO_SAFE_IDENTIFY,
    IdentifyProbe,
    ProbeUnavailable,
    candidates_for_port,
    identify_host,
    identify_hosts,
    identify_pacing,
)
from iaiops.core.discovery.pacing import Pacer
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    CONF_PORT_ONLY,
    L2_IDENTIFY,
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    HostResult,
    PacingPolicy,
    PortResult,
)
from iaiops.core.runtime.session_factory import OTConnectionError, OTProtocolError

pytestmark = pytest.mark.unit


# --- helpers ---------------------------------------------------------------


def host(ip: str = "10.0.0.5", **ports_by_state: object) -> HostResult:
    """``host(open=[502], refused=[102])`` — a HostResult with those verdicts."""
    rows = []
    for state, port_list in ports_by_state.items():
        real = {"open": PORT_OPEN, "refused": PORT_REFUSED, "filtered": PORT_FILTERED}[state]
        rows.extend(PortResult(port=p, state=real) for p in port_list)  # type: ignore[union-attr]
    return HostResult(ip=ip, sources=("tcp",), ports=tuple(rows))


class RecordingProbe:
    """A probe whose behaviour is scripted and whose calls are recorded."""

    def __init__(self, outcome, kind=wirelog.MODBUS_FC43):
        self.outcome = outcome
        self.kind = kind
        self.calls: list[tuple[str, int]] = []

    def __call__(self, ip: str, port: int, timeout_s: float, log: wirelog.WireLog):
        self.calls.append((ip, port))
        log.record(self.kind, host=ip, detail=str(port))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def probe_for(protocol: str, outcome, kind=wirelog.MODBUS_FC43) -> tuple[dict, RecordingProbe]:
    fn = RecordingProbe(outcome, kind)
    entry = IdentifyProbe(protocol=protocol, wire_kind=kind, rationale="test", run=fn)
    return {protocol: entry}, fn


# --- the table's structural invariants -------------------------------------


class TestPlanInvariants:
    def test_no_protocol_that_must_never_be_probed_has_a_probe(self):
        assert not set(IDENTIFY_PLAN) & set(ports.NEVER_IDENTIFIED)

    def test_secsgem_specifically_has_no_probe(self):
        """Named on its own because this one stops a production tool. A fab tool
        typically accepts ONE host connection; taking it evicts the real MES."""
        assert "secsgem" not in IDENTIFY_PLAN
        assert "secsgem" in ports.NEVER_IDENTIFIED

    def test_every_emission_is_pre_declared_in_the_wire_log(self):
        assert {p.wire_kind for p in IDENTIFY_PLAN.values()} <= set(wirelog.KNOWN_KINDS)

    def test_no_protocol_is_both_probeable_and_not(self):
        assert not set(IDENTIFY_PLAN) & set(NO_SAFE_IDENTIFY)

    def test_every_allowlisted_protocol_is_accounted_for(self):
        """No silent holes. An open port that stays unidentified must be
        explainable from the tables — either a probe exists, or there is a
        written reason there is none. 'Nothing happened and we don't say why'
        reads as a bug and destroys trust in the rest of the report."""
        reachable = {
            proto
            for entry in ports.ALLOWLIST
            if entry.transport == ports.TCP
            for proto in entry.protocols
        }
        unexplained = reachable - set(IDENTIFY_PLAN) - set(NO_SAFE_IDENTIFY)
        assert not unexplained, (
            f"{sorted(unexplained)} can be reached on an allowlisted port but neither "
            "has a probe nor a documented reason for having none"
        )

    def test_every_documented_refusal_carries_a_real_reason(self):
        for name, reason in NO_SAFE_IDENTIFY.items():
            assert len(reason) > 60, f"{name}'s reason is too thin to be useful"

    def test_the_preview_promises_exactly_what_the_probes_emit(self):
        """The preview is the document an operator signs, so it must describe the
        probes that will run — not the ones that existed when someone last edited
        a constant.

        The expected set is re-derived here from ``IDENTIFY_PLAN`` rather than
        from ``identify_emissions()``: comparing the production value against the
        production helper that computes it can never fail. Written this way, the
        test fails the moment anyone replaces the derivation with a hand-written
        list and then adds or removes a probe.
        """
        expected = tuple(sorted({p.wire_kind for p in IDENTIFY_PLAN.values()}))
        assert preview.STAGE_EMISSIONS[L2_IDENTIFY] == expected

    def test_validation_rejects_a_forbidden_protocol(self, monkeypatch):
        """The import-time guard is only worth having if it actually fires."""
        bad = dict(IDENTIFY_PLAN)
        bad["secsgem"] = IdentifyProbe(
            protocol="secsgem",
            wire_kind=wirelog.TCP_CONNECT,
            rationale="",
            run=lambda *a: {},
        )
        monkeypatch.setattr(identify, "IDENTIFY_PLAN", bad)
        with pytest.raises(RuntimeError, match="never be probed"):
            identify._validate_plan()

    def test_validation_rejects_an_undeclared_emission(self, monkeypatch):
        bad = dict(IDENTIFY_PLAN)
        bad["modbus"] = IdentifyProbe(
            protocol="modbus",
            wire_kind="secret_new_packet",
            rationale="",
            run=lambda *a: {},
        )
        monkeypatch.setattr(identify, "IDENTIFY_PLAN", bad)
        with pytest.raises(RuntimeError, match="undeclared packet classes"):
            identify._validate_plan()


class TestCandidateSelection:
    def test_modbus_port_offers_modbus(self):
        assert candidates_for_port(502) == ("modbus",)

    def test_port_5000_offers_mtconnect_and_never_secsgem(self):
        """5000 is shared between MTConnect agents and SECS/GEM HSMS. The HTTP
        GET is harmlessly refused by an HSMS listener; a session is not."""
        assert candidates_for_port(5000) == ("mtconnect",)

    def test_a_udp_entry_offers_nothing(self):
        assert candidates_for_port(47808) == ()

    def test_a_port_outside_the_allowlist_offers_nothing(self):
        assert candidates_for_port(22) == ()
        assert candidates_for_port(2222) == ()


# --- outcome mapping -------------------------------------------------------


class TestOutcomeMapping:
    def test_a_clean_answer_confirms_and_carries_identity(self):
        plan, _ = probe_for("modbus", {"vendor": "Schneider", "model": "TM241"})
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        candidate = out.protocols[0]
        assert candidate.confidence == CONF_CONFIRMED
        assert candidate.evidence == wirelog.MODBUS_FC43
        assert out.identity["modbus"]["vendor"] == "Schneider"

    def test_an_in_protocol_refusal_confirms_the_protocol(self):
        """The device ANSWERED, in Modbus, saying 'illegal function'. It is a
        Modbus device whose identity we do not know — a different and much more
        useful statement than 'port 502 was open'."""
        plan, _ = probe_for("modbus", OTProtocolError("illegal function"))
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        candidate = out.protocols[0]
        assert candidate.confidence == CONF_CONFIRMED
        assert candidate.evidence.endswith(":rejected")

    def test_an_in_protocol_refusal_invents_no_vendor(self):
        plan, _ = probe_for("modbus", OTProtocolError("illegal function"))
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        assert out.identity == {}

    def test_a_transport_failure_stays_port_only(self):
        plan, _ = probe_for("modbus", OTConnectionError("connection reset"))
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        candidate = out.protocols[0]
        assert candidate.confidence == CONF_PORT_ONLY
        assert candidate.evidence == "tcp_open"
        assert out.identity == {}

    def test_a_missing_extra_blames_this_machine_not_the_device(self):
        """'Could not identify' would blame a device that was never asked."""
        plan, _ = probe_for("modbus", ProbeUnavailable("modbus extra not installed"))
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        candidate = out.protocols[0]
        assert candidate.confidence == CONF_PORT_ONLY
        assert candidate.evidence == "probe_unavailable"
        assert "not asked" in candidate.detail

    def test_an_unexpected_error_does_not_end_the_scan(self):
        plan, _ = probe_for("modbus", ValueError("driver blew up"))
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        candidate = out.protocols[0]
        assert candidate.confidence == CONF_PORT_ONLY
        assert "ValueError" in candidate.detail

    def test_a_confirmation_with_no_fields_says_so_rather_than_looking_empty(self):
        plan, _ = probe_for("modbus", {})
        out = identify_host(host(open=[502]), log=wirelog.WireLog(), plan=plan)
        assert "no identity fields" in out.protocols[0].detail


# --- what is never touched -------------------------------------------------


class TestWhatIsNeverTouched:
    def test_refused_ports_are_never_probed(self):
        """A refusal already proved the host is alive. Speaking to a closed port
        buys nothing and costs a packet."""
        plan, fn = probe_for("modbus", {"vendor": "x"})
        log = wirelog.WireLog()
        identify_host(host(refused=[502]), log=log, plan=plan)
        assert fn.calls == []
        assert log.total() == 0

    def test_filtered_ports_are_never_probed(self):
        plan, fn = probe_for("modbus", {"vendor": "x"})
        identify_host(host(filtered=[502]), log=wirelog.WireLog(), plan=plan)
        assert fn.calls == []

    def test_a_host_with_nothing_open_is_returned_untouched(self):
        plan, fn = probe_for("modbus", {"vendor": "x"})
        original = host(refused=[502, 102], filtered=[4840])
        log = wirelog.WireLog()
        assert identify_host(original, log=log, plan=plan) is original
        assert log.total() == 0
        assert fn.calls == []

    def test_only_the_open_port_of_a_mixed_host_is_probed(self):
        plan, fn = probe_for("modbus", {"vendor": "x"})
        mixed = host(open=[502], refused=[102], filtered=[4840])
        identify_host(mixed, log=wirelog.WireLog(), plan=plan)
        assert fn.calls == [("10.0.0.5", 502)]


class TestIdentityHandling:
    def test_two_protocols_on_one_host_both_survive(self):
        """A gateway speaking Modbus and OPC-UA is ordinary. Last-write-wins on a
        flat identity dict would silently drop one of them."""
        modbus_plan, _ = probe_for("modbus", {"vendor": "Moxa"})
        opcua_plan, _ = probe_for("opcua", {"name": "Gateway"}, kind=wirelog.OPCUA_GETENDPOINTS)
        plan = {**modbus_plan, **opcua_plan}
        out = identify_host(host(open=[502, 4840]), log=wirelog.WireLog(), plan=plan)
        assert out.identity["modbus"]["vendor"] == "Moxa"
        assert out.identity["opcua"]["name"] == "Gateway"
        assert {c.protocol for c in out.protocols} == {"modbus", "opcua"}

    def test_the_sweep_result_is_otherwise_preserved(self):
        plan, _ = probe_for("modbus", {"vendor": "x"})
        original = host(open=[502])
        out = identify_host(original, log=wirelog.WireLog(), plan=plan)
        assert out.ip == original.ip
        assert out.ports == original.ports
        assert out.sources == original.sources


# --- the wire log ----------------------------------------------------------


class TestWireLog:
    def test_each_probe_is_counted(self):
        plan, _ = probe_for("modbus", {"vendor": "x"})
        log = wirelog.WireLog()
        identify_host(host(open=[502]), log=log, plan=plan)
        assert log.summary() == {wirelog.MODBUS_FC43: 1}

    def test_a_failed_probe_is_still_counted(self):
        """The packet went out whether or not it was answered. A trust page that
        only counts successes is not a trust page."""
        plan, _ = probe_for("modbus", OTConnectionError("timeout"))
        log = wirelog.WireLog()
        identify_host(host(open=[502]), log=log, plan=plan)
        assert log.summary() == {wirelog.MODBUS_FC43: 1}


# --- the S7 slot retry — the only probe that makes two requests ------------


class TestS7SlotRetry:
    def _ops(self, monkeypatch, behaviour):
        from iaiops.connectors.s7 import ops

        seen: list[int] = []

        def fake(target):
            seen.append(target.slot)
            result = behaviour(target.slot)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(ops, "s7_cpu_info", fake)
        return seen

    def test_slot_2_is_tried_when_slot_1_does_not_answer(self, monkeypatch):
        """S7-1200/1500 answer on slot 1, S7-300/400 on slot 2. One guess
        mis-reports half the installed base as 'open port, unidentified'."""
        seen = self._ops(
            monkeypatch,
            lambda slot: (
                OTConnectionError("no route to CPU")
                if slot == 1
                else {"cpu_info": {"ModuleTypeName": "CPU 315-2 PN/DP"}, "cpu_status": "Run"}
            ),
        )
        log = wirelog.WireLog()
        out = identify.identify_host(host(open=[102]), log=log, plan=IDENTIFY_PLAN)
        assert seen == [1, 2]
        assert out.protocols[0].confidence == CONF_CONFIRMED
        assert out.identity["s7"]["model"] == "CPU 315-2 PN/DP"
        assert out.identity["s7"]["vendor"] == "Siemens"
        assert log.summary()[wirelog.S7_CPU_INFO] == 2, "both attempts must be counted"

    def test_an_in_protocol_refusal_does_not_spend_a_second_packet(self, monkeypatch):
        """The CPU answered and declined — the slot was right. Trying the other
        one is a packet spent to learn nothing."""
        seen = self._ops(monkeypatch, lambda slot: OTProtocolError("SZL read denied"))
        log = wirelog.WireLog()
        out = identify.identify_host(host(open=[102]), log=log, plan=IDENTIFY_PLAN)
        assert seen == [1]
        assert log.summary()[wirelog.S7_CPU_INFO] == 1
        assert out.protocols[0].confidence == CONF_CONFIRMED

    def test_both_slots_failing_reports_port_only_with_no_vendor(self, monkeypatch):
        self._ops(monkeypatch, lambda slot: OTConnectionError("timed out"))
        out = identify.identify_host(host(open=[102]), log=wirelog.WireLog(), plan=IDENTIFY_PLAN)
        assert out.protocols[0].confidence == CONF_PORT_ONLY
        assert out.identity == {}

    def test_max_requests_declares_the_retry(self):
        """The preview's estimate must be an upper bound, so the one probe that
        can send twice has to say so."""
        assert IDENTIFY_PLAN["s7"].max_requests == 2
        assert all(p.max_requests == 1 for k, p in IDENTIFY_PLAN.items() if k != "s7")


# --- extractors against realistic connector payloads -----------------------


class TestExtractors:
    """Each probe's mapping, driven through the REAL ops function's return shape.

    The hazard these guard against is the one that already bit once here: a fake
    and its parser agreeing with each other and both being wrong. The shapes
    below are copied from the ops functions' own return statements.
    """

    def test_modbus_promotes_the_three_basic_fields(self, monkeypatch):
        from iaiops.connectors.modbus import ops

        monkeypatch.setattr(
            ops,
            "modbus_read_device_identification",
            lambda t: {
                "unit_id": 1,
                "objects": {"vendor_name": "汇川", "product_code": "AM401", "revision": "2.1"},
                "vendor": "汇川",
                "product_code": "AM401",
                "revision": "2.1",
                "more_follows": False,
            },
        )
        out = identify._probe_modbus("10.0.0.5", 502, 2.0, wirelog.WireLog())
        assert out["vendor"] == "汇川"
        assert out["model"] == "AM401"
        assert out["firmware"] == "2.1"

    def test_opcua_carries_the_security_finding_alongside_identity(self, monkeypatch):
        from iaiops.connectors.opcua import ops

        monkeypatch.setattr(
            ops,
            "opcua_endpoints",
            lambda t: {
                "application_name": "Plant PLC",
                "application_uri": "urn:plc",
                "product_uri": "urn:vendor:prod",
                "endpoint_count": 2,
                "allows_none_security": True,
                "allows_anonymous": True,
            },
        )
        out = identify._probe_opcua("10.0.0.5", 4840, 2.0, wirelog.WireLog())
        assert out["name"] == "Plant PLC"
        assert out["extra"]["allows_none_security"] is True

    def test_mc_names_the_vendor_only_when_the_cpu_answered(self, monkeypatch):
        from iaiops.connectors.mc import ops

        monkeypatch.setattr(
            ops,
            "mc_cpu_status",
            lambda t: {"cpu_type": "Q06UDEH", "cpu_code": "0x4C", "plctype": "Q"},
        )
        out = identify._probe_mc("10.0.0.5", 5007, 2.0, wirelog.WireLog())
        assert out["vendor"] == "Mitsubishi"
        assert out["model"] == "Q06UDEH"

    def test_mc_invents_no_vendor_from_an_empty_answer(self, monkeypatch):
        from iaiops.connectors.mc import ops

        monkeypatch.setattr(ops, "mc_cpu_status", lambda t: {"cpu_type": "", "cpu_code": ""})
        out = identify._probe_mc("10.0.0.5", 5007, 2.0, wirelog.WireLog())
        assert "vendor" not in out

    def test_eip_reads_the_cip_identity_object(self, monkeypatch):
        from iaiops.connectors.eip import ops

        monkeypatch.setattr(
            ops,
            "eip_controller_info",
            lambda t, plctype=None: {
                "plctype": "logix",
                "controller": {
                    "vendor": "Rockwell Automation/Allen-Bradley",
                    "product_name": "1769-L33ER",
                    "serial": "0x60C0FFEE",
                    "revision": {"major": 32, "minor": 11},
                    "name": "Line3_PLC",
                },
                "info_error": "",
            },
        )
        out = identify._probe_eip("10.0.0.5", 44818, 2.0, wirelog.WireLog())
        assert out["model"] == "1769-L33ER"
        assert out["serial"] == "0x60C0FFEE"
        assert out["name"] == "Line3_PLC"

    def test_mtconnect_keeps_only_the_head_of_the_device_tree(self, monkeypatch):
        """The full probe response carries every data item of every component.
        That belongs to L4; an inventory row must not drag it into a database."""
        from iaiops.connectors.mtconnect import ops

        monkeypatch.setattr(
            ops,
            "mtconnect_probe",
            lambda t: {
                "device_count": 1,
                "devices": [
                    {
                        "name": "OKUMA.Lathe",
                        "uuid": "OKUMA-123",
                        "component_count": 40,
                        "components": [{"data_items": [{"id": f"x{i}"} for i in range(500)]}],
                    }
                ],
            },
        )
        out = identify._probe_mtconnect("10.0.0.5", 5000, 2.0, wirelog.WireLog())
        assert out["name"] == "OKUMA.Lathe"
        assert out["serial"] == "OKUMA-123"
        assert "components" not in repr(out), "the component tree must not ride along"

    def test_iolink_reads_the_master_identity(self, monkeypatch):
        from iaiops.connectors.iolink import ops

        monkeypatch.setattr(
            ops,
            "master_info",
            lambda t: {
                "flavor": "iotcore",
                "master": {
                    "vendor": "ifm electronic",
                    "productcode": "AL1350",
                    "serialnumber": "000174512345",
                    "swrevision": "4.2.19",
                    "devicename": "sub-fab-master-1",
                },
            },
        )
        out = identify._probe_iolink("10.0.0.5", 80, 2.0, wirelog.WireLog())
        assert out["vendor"] == "ifm electronic"
        assert out["model"] == "AL1350"
        assert out["serial"] == "000174512345"


class TestIdentityAssembly:
    def test_absent_fields_are_dropped_not_blanked(self):
        """An empty string is not 'unknown vendor' — it is an absent column, and
        the report must render nothing rather than guess."""
        out = identify._identity(vendor="", model="TM241")
        assert out == {"model": "TM241"}

    def test_whitespace_only_counts_as_absent(self):
        assert identify._identity(vendor="   ") == {}

    def test_extras_are_kept_but_separated(self):
        out = identify._identity(vendor="x", endpoint_count=3, empty="")
        assert out["extra"] == {"endpoint_count": 3}


# --- run-level behaviour ---------------------------------------------------


class TestIdentifyHosts:
    def test_unidentified_open_ports_are_explained_not_hidden(self):
        plan, _ = probe_for("modbus", OTConnectionError("timeout"))
        _, notes = identify_hosts([host(open=[502])], plan=plan)
        assert any("port only" in n for n in notes)
        assert any("not an identification" in n for n in notes)

    def test_a_fully_identified_run_says_nothing(self):
        plan, _ = probe_for("modbus", {"vendor": "x"})
        _, notes = identify_hosts([host(open=[502])], plan=plan)
        assert notes == ()

    def test_a_backed_off_host_stops_being_probed(self):
        """Three consecutive failures and the host is left alone for the run —
        the same brake the sweep uses, for a heavier kind of request."""
        plan, fn = probe_for("modbus", OTConnectionError("timeout"))
        pacing = PacingPolicy(host_backoff_after=1, per_host_gap_ms=0, identify_gap_ms=0)
        hosts = [host("10.0.0.5", open=[502]), host("10.0.0.5", open=[502])]
        identify_hosts(hosts, pacing=pacing, plan=plan)
        assert len(fn.calls) == 1, "the second pass at a backed-off host must not run"

    def test_a_dying_segment_aborts_with_a_note(self):
        plan, _ = probe_for("modbus", OTConnectionError("timeout"))
        pacing = PacingPolicy(
            segment_abort_after=2, host_backoff_after=99, per_host_gap_ms=0, identify_gap_ms=0
        )
        hosts = [host(f"10.0.0.{i}", open=[502]) for i in range(6)]
        out, notes = identify_hosts(hosts, pacing=pacing, plan=plan)
        assert any("aborting" in n for n in notes)
        assert len(out) < len(hosts), "an abort must actually stop, not just annotate"

    def test_identification_reuses_the_identify_gap_not_the_connect_gap(self):
        """An identify call is answered by a control CPU, not by a kernel, so the
        same host gets the longer of the two gaps between calls."""
        policy = PacingPolicy(per_host_gap_ms=250, identify_gap_ms=1500)
        assert identify_pacing(policy).per_host_gap_ms == 1500

    def test_the_pacer_is_actually_applied(self, monkeypatch):
        seen: list[str] = []
        real = Pacer.probe

        def spy(self, host_ip):
            seen.append(host_ip)
            return real(self, host_ip)

        monkeypatch.setattr(Pacer, "probe", spy)
        plan, _ = probe_for("modbus", {"vendor": "x"})
        identify_hosts([host(open=[502])], plan=plan)
        assert seen == ["10.0.0.5"]


class TestEveryProbeCanActuallyRun:
    """The generic version of a bug that unit tests with fakes cannot see.

    ``_target`` builds a real ``TargetConfig``, and ``host``/``port`` are both
    connection FIELDS of one — so a probe passing them alongside a positional
    parameter of the same name raises ``TypeError`` before a packet is sent. That
    is a probe which is dead against every live device while every test that
    stubs it out stays green. This walks the whole table, so a probe added next
    year is covered without anyone remembering to cover it.
    """

    #: protocol -> (ops module path, function name). Asserted complete below, so
    #: a new probe fails here rather than shipping unexercised.
    OPS = {
        "modbus": ("iaiops.connectors.modbus.ops", "modbus_read_device_identification"),
        "opcua": ("iaiops.connectors.opcua.ops", "opcua_endpoints"),
        "s7": ("iaiops.connectors.s7.ops", "s7_cpu_info"),
        "ethernetip": ("iaiops.connectors.eip.ops", "eip_controller_info"),
        "mc": ("iaiops.connectors.mc.ops", "mc_cpu_status"),
        "mtconnect": ("iaiops.connectors.mtconnect.ops", "mtconnect_probe"),
        "iolink": ("iaiops.connectors.iolink.ops", "master_info"),
    }

    def test_the_table_is_complete(self):
        assert set(self.OPS) == set(IDENTIFY_PLAN), (
            "a probe was added or removed without updating this test's ops map — "
            "which means it is not being exercised against a real TargetConfig"
        )

    @pytest.mark.parametrize("protocol", sorted(OPS))
    def test_the_probe_builds_a_real_target_and_reaches_its_ops_call(self, protocol, monkeypatch):
        import importlib

        module_path, func_name = self.OPS[protocol]
        module = importlib.import_module(module_path)
        seen: list[object] = []

        def spy(target, *args, **kwargs):
            seen.append(target)
            return {}

        monkeypatch.setattr(module, func_name, spy)

        probe = IDENTIFY_PLAN[protocol]
        log = wirelog.WireLog()
        probe.run("10.0.0.5", 502, 2.0, log)

        assert seen, f"{protocol} never reached {func_name}"
        target = seen[0]
        assert target.protocol in (protocol, "ethernetip")
        assert target.timeout_s == 2.0
        assert log.summary().get(probe.wire_kind, 0) >= 1
