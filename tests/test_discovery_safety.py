"""Pacing, wire log, and the no-write guard.

The guard tests are mutation-checked by construction: each one plants the exact
mistake it exists to catch (a write import, an eager connector import, an
undeclared packet class) and asserts the machinery refuses it. A guard that has
never been seen to fail is not evidence.
"""

from __future__ import annotations

import textwrap
import threading

import pytest

from iaiops.core.discovery import guard, wirelog
from iaiops.core.discovery.pacing import (
    HostBackedOff,
    HostGate,
    Pacer,
    SegmentHealth,
    SegmentUnhealthy,
    TokenBucket,
    shuffled,
)
from iaiops.core.discovery.types import PacingPolicy

pytestmark = pytest.mark.unit


class FakeClock:
    """Virtual time: the pacing logic runs for real, the waiting does not."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class TestTokenBucket:
    def test_initial_burst_is_bounded_by_the_rate(self):
        clock = FakeClock()
        bucket = TokenBucket(10.0, monotonic=clock.monotonic, sleep=clock.sleep)
        for _ in range(10):
            assert bucket.acquire() == 0.0
        assert bucket.acquire() > 0.0, "the 11th connect in a second must wait"

    def test_refills_over_time(self):
        clock = FakeClock()
        bucket = TokenBucket(10.0, monotonic=clock.monotonic, sleep=clock.sleep)
        for _ in range(10):
            bucket.acquire()
        clock.now += 1.0
        assert bucket.acquire() == 0.0

    def test_sustained_rate_matches_the_policy(self):
        clock = FakeClock()
        bucket = TokenBucket(5.0, monotonic=clock.monotonic, sleep=clock.sleep)
        for _ in range(25):
            bucket.acquire()
        # 25 connects at 5/s, with a 5-token burst, is ~4 seconds of waiting.
        assert 3.5 <= clock.now <= 4.5

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError):
            TokenBucket(0)

    def test_a_rate_below_one_per_second_still_grants(self):
        """A sub-1/s rate is the gentlest setting the policy allows, and the one
        a fragile controller deserves. The bucket must still hand out whole
        tokens: sizing capacity to the rate means it saturates below 1 and the
        scan waits forever for a token that can never arrive."""
        clock = FakeClock()
        bucket = TokenBucket(0.5, monotonic=clock.monotonic, sleep=clock.sleep)
        waited = bucket.acquire()
        assert waited >= 0.0
        assert clock.now <= 4.0, "one token at 0.5/s is ~2s of waiting, not a hang"

    def test_a_broken_refill_loop_raises_instead_of_spinning(self, monkeypatch):
        """A hung limiter is a hung scanner. On a plant floor a stuck process is
        worse than a loud error — and in CI a hang is worse than a red test.
        (The float-tolerance bug this replaces did exactly that.)"""
        clock = FakeClock()
        bucket = TokenBucket(10.0, monotonic=clock.monotonic, sleep=lambda _s: None)
        # sleep() that never advances time is the pathological case: no refill
        # can ever happen, so the loop must give up rather than spin.
        with pytest.raises(RuntimeError, match="Refusing to spin"):
            for _ in range(50):
                bucket.acquire()


class TestHostGate:
    def test_enforces_the_gap_between_two_probes_of_one_host(self):
        clock = FakeClock()
        gate = HostGate(250, monotonic=clock.monotonic, sleep=clock.sleep)
        with gate.hold("10.0.0.5"):
            pass
        with gate.hold("10.0.0.5"):
            pass
        assert clock.slept == [0.25]

    def test_different_hosts_do_not_wait_on_each_other(self):
        clock = FakeClock()
        gate = HostGate(250, monotonic=clock.monotonic, sleep=clock.sleep)
        with gate.hold("10.0.0.5"):
            pass
        with gate.hold("10.0.0.6"):
            pass
        assert clock.slept == []

    def test_only_one_probe_per_host_is_in_flight(self):
        gate = HostGate(0)
        overlapped = []
        inside = threading.Event()

        def worker(tag: str) -> None:
            with gate.hold("10.0.0.5"):
                overlapped.append(f"enter-{tag}")
                inside.set()
                overlapped.append(f"exit-{tag}")

        t1 = threading.Thread(target=worker, args=("a",))
        t2 = threading.Thread(target=worker, args=("b",))
        t1.start()
        inside.wait(timeout=2)
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        # Never enter-a, enter-b, exit-a: the pairs must not interleave.
        assert overlapped[0].startswith("enter")
        assert overlapped[1].startswith("exit")
        assert overlapped[1][-1] == overlapped[0][-1]


class TestSegmentHealth:
    def test_a_host_is_dropped_after_repeated_failures(self):
        health = SegmentHealth(host_backoff_after=3, segment_abort_after=100)
        for _ in range(2):
            health.record_error("10.0.0.5")
        assert health.is_blocked("10.0.0.5") is False
        health.record_error("10.0.0.5")
        assert health.is_blocked("10.0.0.5") is True
        assert health.blocked_hosts == ("10.0.0.5",)

    def test_success_clears_a_hosts_error_streak(self):
        health = SegmentHealth(host_backoff_after=3, segment_abort_after=100)
        health.record_error("10.0.0.5")
        health.record_error("10.0.0.5")
        health.record_ok("10.0.0.5")
        health.record_error("10.0.0.5")
        assert health.is_blocked("10.0.0.5") is False

    def test_a_failing_segment_aborts_the_run(self):
        health = SegmentHealth(host_backoff_after=99, segment_abort_after=5)
        for i in range(5):
            health.record_error(f"10.0.0.{i}")
        with pytest.raises(SegmentUnhealthy, match="aborting"):
            health.check_segment()

    def test_the_abort_message_blames_us_first(self):
        """If a whole segment is failing, the likeliest cause is the scan."""
        health = SegmentHealth(host_backoff_after=99, segment_abort_after=1)
        health.record_error("10.0.0.1")
        with pytest.raises(SegmentUnhealthy) as excinfo:
            health.check_segment()
        assert "disturbing the network" in str(excinfo.value)


class TestPacer:
    def test_probe_refuses_a_backed_off_host(self):
        clock = FakeClock()
        pacer = Pacer(
            PacingPolicy(host_backoff_after=1), monotonic=clock.monotonic, sleep=clock.sleep
        )
        pacer.health.record_error("10.0.0.5")
        with pytest.raises(HostBackedOff):
            with pacer.probe("10.0.0.5"):
                pass

    def test_probe_releases_its_slot_even_when_the_body_raises(self):
        clock = FakeClock()
        pacer = Pacer(PacingPolicy(max_concurrency=1), monotonic=clock.monotonic, sleep=clock.sleep)
        with pytest.raises(RuntimeError):
            with pacer.probe("10.0.0.5"):
                raise RuntimeError("probe blew up")
        # The slot must be free, or the whole scan deadlocks on the next host.
        with pacer.probe("10.0.0.6"):
            pass


class TestHostOrdering:
    def test_shuffle_is_deterministic_for_a_seed(self):
        hosts = [f"10.0.0.{i}" for i in range(1, 30)]
        assert shuffled(hosts, seed=42) == shuffled(hosts, seed=42)

    def test_shuffle_is_not_sequential(self):
        """A marching sweep concentrates on one switch's port group."""
        hosts = [f"10.0.0.{i}" for i in range(1, 60)]
        assert shuffled(hosts, seed=7) != tuple(hosts)

    def test_shuffle_keeps_every_host(self):
        hosts = [f"10.0.0.{i}" for i in range(1, 30)]
        assert sorted(shuffled(hosts, seed=3)) == sorted(hosts)


class TestWireLog:
    def test_an_undeclared_packet_class_is_refused(self):
        """A stage cannot start emitting something the report has never heard of."""
        log = wirelog.WireLog()
        with pytest.raises(wirelog.UnknownWireKind, match="declared"):
            log.record("syn_flood")

    def test_counts_are_exact_even_past_the_detail_cap(self):
        log = wirelog.WireLog(event_cap=10)
        for _ in range(100):
            log.record(wirelog.TCP_CONNECT, host="10.0.0.5")
        assert log.summary() == {wirelog.TCP_CONNECT: 100}
        assert len(log.events()) == 10
        assert log.events_dropped == 90

    def test_report_carries_the_never_done_list(self):
        log = wirelog.WireLog()
        log.record(wirelog.MODBUS_FC43, host="10.0.0.5")
        report = log.report()
        assert report["total_emissions"] == 1
        assert any("No writes of any kind" in line for line in report["never_done"])
        assert report["by_class"][0]["description"]

    def test_every_known_kind_is_described(self):
        for kind, description in wirelog.KNOWN_KINDS.items():
            assert description.strip(), f"{kind} has no human description"

    def test_is_thread_safe(self):
        log = wirelog.WireLog(event_cap=100000)
        threads = [
            threading.Thread(target=lambda: [log.record(wirelog.TCP_CONNECT) for _ in range(200)])
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert log.total() == 1600


class TestNoWritePathGuard:
    def test_the_real_package_has_no_write_path(self):
        guard.assert_no_write_path()

    def test_the_guard_catches_a_planted_write_import(self, tmp_path):
        (tmp_path / "bad.py").write_text(
            textwrap.dedent(
                """
                def do_it(target):
                    from iaiops.connectors.s7.ops import s7_write_db
                    return s7_write_db(target, db=1, dtype="INT", start=0, value=5)
                """
            )
        )
        findings = guard.audit_source(tmp_path)
        kinds = {f.kind for f in findings}
        assert "write_symbol" in kinds
        with pytest.raises(AssertionError, match="no write path"):
            guard.assert_no_write_path(tmp_path)

    def test_the_guard_catches_an_eager_connector_import(self, tmp_path):
        """Connector ops modules hold writes beside reads, so importing one at
        module scope puts a write one attribute lookup away."""
        (tmp_path / "eager.py").write_text("from iaiops.connectors.modbus import ops\n")
        findings = guard.audit_source(tmp_path)
        assert [f.kind for f in findings] == ["eager_connector_import"]

    def test_a_lazy_read_import_inside_a_function_is_allowed(self):
        """The identify stage has to reach the connectors somehow; lazily, inside
        the function that needs the read, is the repo's existing convention."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text(
                textwrap.dedent(
                    """
                    def identify(target):
                        from iaiops.connectors.modbus.ops import modbus_read_device_information
                        return modbus_read_device_information(target)
                    """
                )
            )
            assert guard.audit_source(root) == ()

    def test_guard_covers_every_registered_write_tool(self):
        """If upstream adds an 11th write tool, this fails rather than silently
        leaving it off the forbidden list."""
        import importlib.util
        from pathlib import Path

        manifest = Path(__file__).with_name("test_write_approval_contract.py")
        spec = importlib.util.spec_from_file_location("_write_manifest", manifest)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        registered = {ops_attr for _mod, ops_attr, _kw in module.WRITE_TOOLS.values()}
        missing = registered - guard.FORBIDDEN_WRITE_SYMBOLS
        assert not missing, (
            f"these registered write tools are not in FORBIDDEN_WRITE_SYMBOLS: {sorted(missing)}"
        )

    def test_a_generically_named_write_is_caught_by_import_not_by_identifier(self, tmp_path):
        """The BAS write is named just ``command``. Scanning for that bare
        identifier would flag any local variable of the same name and train
        reviewers to ignore the guard, so the import target is what's checked."""
        assert "command" in guard.FORBIDDEN_WRITE_SYMBOLS
        assert "command" in guard._AMBIGUOUS_SYMBOLS

        (tmp_path / "innocent.py").write_text(
            "def run(command):\n    return {'command': command}\n"
        )
        assert guard.audit_source(tmp_path) == ()

        (tmp_path / "innocent.py").write_text(
            "def run(t):\n"
            "    from iaiops.connectors.bas.ops import command\n"
            "    return command(t)\n"
        )
        findings = guard.audit_source(tmp_path)
        assert [f.kind for f in findings] == ["write_import"]

    def test_a_write_that_does_not_exist_upstream_yet_is_already_forbidden(self, tmp_path):
        """Modbus and OPC-UA are read-only today; if a write lands there without
        also being registered as an MCP tool, the sync test above would miss it."""
        (tmp_path / "future.py").write_text(
            "def run(t):\n"
            "    from iaiops.connectors.modbus import ops\n"
            "    return ops.modbus_write_register(t, 1, 2)\n"
        )
        kinds = {f.kind for f in guard.audit_source(tmp_path)}
        assert "write_symbol" in kinds

    def test_only_the_guard_module_itself_is_exempt(self):
        assert guard._SELF == "guard.py"
