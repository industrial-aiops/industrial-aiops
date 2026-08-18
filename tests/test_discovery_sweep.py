"""The L1 sweep, against real local listeners and a fake connector.

Two layers on purpose. The fake connector drives the verdict logic exactly
(including errno cases a laptop cannot produce on demand), and a real
``socket.socket`` listener matrix proves the actual connect path works against
the kernel's own stack rather than only against our idea of it.

The timeout path here is driven through the fake, because a genuine ``filtered``
needs a real firewall rule. That case is NOT left as a promise: it is covered by
``test_discovery_sweep_filtered_live.py``, which installs an actual iptables DROP
inside a container netns and asserts all three verdicts against the kernel.
"""

from __future__ import annotations

import errno
import socket
import threading

import pytest

from iaiops.core.discovery import wirelog
from iaiops.core.discovery.sweep import (
    diagnose_empty_sweep,
    probe_port,
    sweep_hosts,
)
from iaiops.core.discovery.types import (
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    HostResult,
    PacingPolicy,
    PortResult,
)

pytestmark = pytest.mark.unit

FAST = PacingPolicy(connects_per_second=100.0, max_concurrency=4, per_host_gap_ms=0)


class FakeSocket:
    def __init__(self) -> None:
        self.shutdown_called = False
        self.closed = False

    def shutdown(self, how: int) -> None:
        self.shutdown_called = True

    def close(self) -> None:
        self.closed = True


def connector_map(behaviour: dict[tuple[str, int], object]):
    """Build a connector whose response per (host, port) is scripted."""

    def connect(address, timeout=None):
        result = behaviour.get(tuple(address))
        if result is None:
            raise OSError(errno.ECONNREFUSED, "Connection refused")
        if isinstance(result, BaseException):
            raise result
        return result

    return connect


class TestProbeVerdicts:
    def test_open_closes_the_socket_and_sends_no_payload(self):
        sock = FakeSocket()
        outcome = probe_port(
            "10.0.0.5", 502, timeout_s=1.0, connector=connector_map({("10.0.0.5", 502): sock})
        )
        assert outcome.state == PORT_OPEN
        assert sock.shutdown_called and sock.closed
        # There is no send/sendall on the fake — a payload would have raised.

    def test_refused_means_the_host_is_alive(self):
        outcome = probe_port("10.0.0.5", 502, timeout_s=1.0, connector=connector_map({}))
        assert outcome.state == PORT_REFUSED
        assert outcome.proves_host_alive is True

    def test_timeout_is_filtered_and_proves_nothing(self):
        conn = connector_map({("10.0.0.9", 502): TimeoutError()})
        outcome = probe_port("10.0.0.9", 502, timeout_s=1.0, connector=conn)
        assert outcome.state == PORT_FILTERED
        assert outcome.proves_host_alive is False
        assert outcome.error == "timeout"

    def test_host_unreachable_is_filtered_not_alive(self):
        """A router answered on the host's behalf; the host itself said nothing."""
        conn = connector_map({("10.0.0.9", 502): OSError(errno.EHOSTUNREACH, "No route to host")})
        outcome = probe_port("10.0.0.9", 502, timeout_s=1.0, connector=conn)
        assert outcome.state == PORT_FILTERED
        assert outcome.proves_host_alive is False
        assert "unreachable" in outcome.error

    def test_an_unexpected_error_never_raises_and_never_invents_a_verdict(self):
        conn = connector_map({("10.0.0.9", 502): OSError(errno.EACCES, "Permission denied")})
        outcome = probe_port("10.0.0.9", 502, timeout_s=1.0, connector=conn)
        assert outcome.state == PORT_FILTERED
        assert "Permission denied" in outcome.error

    def test_close_still_happens_when_shutdown_fails(self):
        class RudeSocket(FakeSocket):
            def shutdown(self, how: int) -> None:
                raise OSError(errno.ENOTCONN, "Not connected")

        sock = RudeSocket()
        outcome = probe_port(
            "10.0.0.5", 502, timeout_s=1.0, connector=connector_map({("10.0.0.5", 502): sock})
        )
        assert outcome.state == PORT_OPEN
        assert sock.closed, "a peer that closed first must not leak our socket"


class TestSweep:
    def test_only_the_given_ports_are_touched(self):
        touched: list[tuple[str, int]] = []

        def spy(address, timeout=None):
            touched.append(tuple(address))
            raise OSError(errno.ECONNREFUSED, "Connection refused")

        sweep_hosts(["10.0.0.1", "10.0.0.2"], [502, 4840], pacing=FAST, connector=spy)
        assert sorted(touched) == [
            ("10.0.0.1", 502),
            ("10.0.0.1", 4840),
            ("10.0.0.2", 502),
            ("10.0.0.2", 4840),
        ]

    def test_every_connect_is_recorded_in_the_wire_log(self):
        log = wirelog.WireLog()
        sweep_hosts(
            ["10.0.0.1", "10.0.0.2"], [502], pacing=FAST, log=log, connector=connector_map({})
        )
        assert log.summary() == {wirelog.TCP_CONNECT: 2}

    def test_results_carry_the_port_verdicts(self):
        sock = FakeSocket()
        conn = connector_map({("10.0.0.1", 502): sock})
        results, _notes = sweep_hosts(["10.0.0.1"], [502, 4840], pacing=FAST, connector=conn)
        states = {p.port: p.state for p in results[0].ports}
        assert states == {502: PORT_OPEN, 4840: PORT_REFUSED}

    def test_a_repeatedly_failing_host_is_dropped_and_reported(self):
        conn = connector_map({("10.0.0.9", p): TimeoutError() for p in (102, 502, 4840, 4843)})
        pacing = PacingPolicy(
            connects_per_second=100.0, max_concurrency=1, per_host_gap_ms=0, host_backoff_after=2
        )
        _results, notes = sweep_hosts(
            ["10.0.0.9"], [102, 502, 4840, 4843], pacing=pacing, connector=conn
        )
        assert any("dropped after repeated failures" in n for n in notes)

    def test_a_failing_segment_aborts_with_a_note_not_a_quiet_partial(self):
        def always_timeout(address, timeout=None):
            raise TimeoutError()

        pacing = PacingPolicy(
            connects_per_second=100.0,
            max_concurrency=1,
            per_host_gap_ms=0,
            host_backoff_after=99,
            segment_abort_after=3,
        )
        hosts = [f"10.0.0.{i}" for i in range(1, 12)]
        _results, notes = sweep_hosts(hosts, [502], pacing=pacing, connector=always_timeout)
        assert any("aborting" in n for n in notes), notes

    def test_host_order_is_shuffled_but_reproducible(self):
        seen: list[list[str]] = []

        def spy_factory(sink: list[str]):
            def spy(address, timeout=None):
                sink.append(address[0])
                raise OSError(errno.ECONNREFUSED, "refused")

            return spy

        hosts = [f"10.0.0.{i}" for i in range(1, 40)]
        for _ in range(2):
            sink: list[str] = []
            sweep_hosts(
                hosts,
                [502],
                pacing=PacingPolicy(
                    connects_per_second=100.0, max_concurrency=1, per_host_gap_ms=0
                ),
                seed=11,
                connector=spy_factory(sink),
            )
            seen.append(sink)
        assert seen[0] == seen[1], "same seed must reproduce the order"
        assert seen[0] != hosts, "a marching sweep hammers one switch's port group"

    def test_probes_interleave_hosts_rather_than_draining_one(self):
        """Queueing one host's ports back to back lets the host gate serialise them
        while they occupy the whole concurrency budget — throughput collapses and
        the preview's duration estimate, which an operator agreed a maintenance
        window on, becomes wrong. With concurrency 1 the execution order is the
        submission order, so this is deterministic."""
        order: list[str] = []

        def spy(address, timeout=None):
            order.append(address[0])
            raise OSError(errno.ECONNREFUSED, "refused")

        hosts = [f"10.0.0.{i}" for i in range(1, 6)]
        sweep_hosts(
            hosts,
            [102, 502, 4840],
            pacing=PacingPolicy(connects_per_second=100.0, max_concurrency=1, per_host_gap_ms=0),
            connector=spy,
        )
        assert len(order) == 15
        back_to_back = sum(1 for a, b in zip(order, order[1:], strict=False) if a == b)
        assert back_to_back == 0, f"consecutive probes hit the same host: {order}"

    def test_the_host_gap_does_not_serialise_the_whole_scan(self):
        """A generous bound, not a tight one: the point is that N hosts with a
        per-host gap do not add up, they overlap."""
        import time

        def refuse(address, timeout=None):
            raise OSError(errno.ECONNREFUSED, "refused")

        hosts = [f"10.0.0.{i}" for i in range(1, 9)]
        ports = [102, 502, 4840, 4843]
        gap_s = 0.2
        pacing = PacingPolicy(
            connects_per_second=100.0, max_concurrency=4, per_host_gap_ms=int(gap_s * 1000)
        )
        started = time.monotonic()
        sweep_hosts(hosts, ports, pacing=pacing, connector=refuse)
        elapsed = time.monotonic() - started
        fully_serialised = len(hosts) * len(ports) * gap_s  # 6.4s
        assert elapsed < fully_serialised / 2, (
            f"{elapsed:.2f}s — the per-host gaps are adding up instead of overlapping"
        )

    def test_one_odd_probe_does_not_end_the_run(self):
        def flaky(address, timeout=None):
            if address[0] == "10.0.0.2":
                raise ValueError("something unexpected inside the connector")
            raise OSError(errno.ECONNREFUSED, "refused")

        results, _notes = sweep_hosts(
            ["10.0.0.1", "10.0.0.2", "10.0.0.3"], [502], pacing=FAST, connector=flaky
        )
        assert {r.ip for r in results} == {"10.0.0.1", "10.0.0.2", "10.0.0.3"}


class TestRealLocalListeners:
    """The actual connect path, against the kernel's own stack."""

    @pytest.fixture
    def listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port = sock.getsockname()[1]
        stop = threading.Event()

        def serve() -> None:
            sock.settimeout(0.2)
            while not stop.is_set():
                try:
                    conn, _ = sock.accept()
                except (TimeoutError, OSError):
                    continue
                conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        yield port
        stop.set()
        thread.join(timeout=2)
        sock.close()

    def test_a_real_listener_reads_as_open(self, listener):
        outcome = probe_port("127.0.0.1", listener, timeout_s=2.0)
        assert outcome.state == PORT_OPEN
        assert outcome.rtt_ms is not None

    def test_a_real_closed_port_reads_as_refused(self):
        # Bind then close to get a port that is very likely unused.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        outcome = probe_port("127.0.0.1", port, timeout_s=2.0)
        assert outcome.state == PORT_REFUSED
        assert outcome.proves_host_alive is True

    def test_sweeping_a_real_mixed_matrix(self, listener):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
        sock.close()

        results, _notes = sweep_hosts(["127.0.0.1"], [listener, closed_port], pacing=FAST)
        states = {p.port: p.state for p in results[0].ports}
        assert states[listener] == PORT_OPEN
        assert states[closed_port] == PORT_REFUSED


class TestEmptySweepDiagnosis:
    def test_a_completely_silent_sweep_blames_the_vlan_and_the_cidr(self):
        notes = diagnose_empty_sweep([])
        assert notes and "VLAN" in notes[0] and "prefix" in notes[0]

    def test_alive_but_refusing_is_reported_as_a_finding(self):
        hosts = [
            HostResult(ip="10.0.0.1", ports=(PortResult(port=502, state=PORT_REFUSED),)),
        ]
        notes = diagnose_empty_sweep(hosts)
        assert any("ALIVE" in n and "not a failure" in n for n in notes)

    def test_filtered_only_is_reported_as_probably_an_acl(self):
        hosts = [
            HostResult(ip="10.0.0.9", ports=(PortResult(port=502, state=PORT_FILTERED),)),
        ]
        notes = diagnose_empty_sweep(hosts)
        assert any("firewall or ACL" in n for n in notes)

    def test_the_two_diagnoses_are_never_merged(self):
        """Alive-but-refusing and silently-dropped are different things to act on."""
        hosts = [
            HostResult(ip="10.0.0.1", ports=(PortResult(port=502, state=PORT_REFUSED),)),
            HostResult(ip="10.0.0.9", ports=(PortResult(port=502, state=PORT_FILTERED),)),
        ]
        notes = diagnose_empty_sweep(hosts)
        assert len(notes) == 2
