"""One connection per RUN, not one per sample.

Measured against a real device across a LAN: collection at 500ms over two tags
opened **3.7 TCP connections a second**, leaving ~110 sockets in TIME_WAIT.
Extrapolated to the assessment run this feature exists for — three tags at 1s for
a week — that is **1.8 million connections**.

The client survives it; TIME_WAIT is bounded by rate times timeout and does not
grow. **The PLC is the risk, and it is a risk this codebase cannot test.** Real
Modbus devices commonly cap concurrent connections in the single digits, and some
Ethernet modules are documented to exhaust their socket table under rapid
connect/disconnect and need a power cycle. A week of churn against a device that
tolerates it is fine; against one that does not, the tool has taken the line down
while measuring how often the line goes down.

Per-call sessions remain right for what they were designed for — a CLI command
that reads one register should not hold a connection open. This is additive: a
protocol that can read inside a session does so, and one that cannot keeps the
existing behaviour rather than being excluded from collection.
"""

from __future__ import annotations

import pytest

from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.runner import run_collection

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds if seconds > 0 else 1.0


class CountingSession:
    """A session builder that records how often a connection was opened."""

    def __init__(self, fail_first: int = 0):
        self.opens = 0
        self.closes = 0
        self.fail_first = fail_first

    def __call__(self, _target):
        self.opens += 1
        if self.opens <= self.fail_first:
            raise ConnectionError("PLC refused the connection")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closes += 1
        return False


def plan(tags=("a", "b"), duration_s=10, interval_ms=1000):
    return CollectionPlan(
        endpoint="line1", tags=tags, duration_s=duration_s, interval_ms=interval_ms
    )


class TestOneConnectionPerRun:
    def test_a_ten_sample_run_opens_one_connection(self, tmp_path):
        session = CountingSession()
        run_collection(
            plan(),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert session.opens == 1, f"opened {session.opens} connections for one run"

    def test_the_connection_is_closed_when_the_run_ends(self, tmp_path):
        session = CountingSession()
        run_collection(
            plan(),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert session.closes == 1

    def test_the_reader_is_given_the_live_client_not_the_target(self, tmp_path):
        session = CountingSession()
        seen = []
        run_collection(
            plan(tags=("a",), duration_s=3),
            target="THE-TARGET",
            reader=lambda client, ref: (seen.append(client) or 1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert seen and all(c is session for c in seen)


class TestWithoutASessionNothingChanges:
    def test_the_target_is_passed_through_when_there_is_no_session(self, tmp_path):
        """A protocol with no session-scoped read keeps the existing behaviour
        rather than being dropped from collection."""
        seen = []
        run_collection(
            plan(tags=("a",), duration_s=3),
            target="THE-TARGET",
            reader=lambda t, ref: (seen.append(t) or 1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
        )
        assert seen == ["THE-TARGET"] * len(seen)

    def test_samples_still_land(self, tmp_path):
        from iaiops.core.sink.sqlite_local import store_coverage

        db = tmp_path / "d.db"
        run_collection(
            plan(tags=("a",), duration_s=5),
            target=object(),
            reader=lambda t, ref: (1.0, ""),
            db_path=db,
            clock=FakeClock(),
        )
        assert store_coverage(db)["samples"] == 5


class TestALostConnectionIsBlindTimeNotDowntime:
    def test_a_refused_connection_does_not_end_the_run(self, tmp_path):
        """A week-long run must survive the PLC blinking."""
        session = CountingSession(fail_first=1)
        result = run_collection(
            plan(tags=("a",), duration_s=5),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert result.stopped_because == "duration_reached"

    def test_the_failed_connection_becomes_a_gap(self, tmp_path):
        session = CountingSession(fail_first=1)
        result = run_collection(
            plan(tags=("a",), duration_s=5),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert result.gaps
        assert "refused" in result.gaps[0]["reason"].lower()

    def test_it_reconnects_and_keeps_collecting(self, tmp_path):
        session = CountingSession(fail_first=1)
        result = run_collection(
            plan(tags=("a",), duration_s=6),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert session.opens >= 2, "a run that never retries the connection is not a run"
        assert result.samples_written > 0

    def test_a_single_failed_connect_that_retries_at_once_costs_no_samples(self, tmp_path):
        """Coverage counts SAMPLES missed, not connection attempts. One refused
        connect followed by an immediate successful retry loses nothing, and
        denting coverage for it would understate a run that actually worked.
        The failure is still recorded as a gap."""
        session = CountingSession(fail_first=1)
        result = run_collection(
            plan(tags=("a",), duration_s=6),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert result.coverage_pct == 100.0
        assert result.gaps

    def test_a_device_that_stays_down_dents_coverage(self, tmp_path):
        """Iterations pass with nothing collected, and that IS lost coverage."""
        session = CountingSession(fail_first=3)
        result = run_collection(
            plan(tags=("a",), duration_s=6),
            target=object(),
            reader=lambda _c, ref: (1.0, ""),
            db_path=tmp_path / "d.db",
            clock=FakeClock(),
            session_builder=session,
        )
        assert result.coverage_pct < 100.0
        assert result.samples_written > 0, "it must recover, not just give up"


class TestASessionReadNeverAssumesTheDevice:
    """The mistake this guards against was made in this very change.

    A session-scoped read receives a live client and nothing else, while Modbus
    needs a unit id per request. The first draft wrote
    `getattr(client, "_iaiops_unit", 1)` — an attribute that did not exist, so
    every read would have silently addressed unit 1. On a site using another
    unit that does not fail: it returns plausible values from a DIFFERENT device.

    The session now attaches the unit at open time and the reader refuses
    without it.
    """

    def test_the_session_attaches_the_unit_id_to_the_client(self):
        from iaiops.core.runtime.connection import _prepare_modbus

        class Client:
            pass

        class Target:
            unit_id = 7

        client = Client()
        _prepare_modbus(client, Target())
        assert client.iaiops_unit_id == 7

    def test_a_client_without_a_unit_id_is_refused_not_defaulted(self):
        from iaiops.core.runtime.capabilities import _session_read_modbus

        class Bare:
            def read_holding_registers(self, *a, **k):  # pragma: no cover - must not run
                raise AssertionError("the read must not happen without a unit id")

        with pytest.raises(ValueError, match="(?i)unit id"):
            _session_read_modbus(Bare(), "0")

    def test_the_declared_unit_reaches_the_wire(self):
        from iaiops.core.runtime.capabilities import _session_read_modbus

        seen = {}

        class Client:
            iaiops_unit_id = 7

            def read_holding_registers(self, address, count=1, device_id=None):
                seen.update(address=address, device_id=device_id)
                return type("R", (), {"isError": lambda s: False, "registers": [42]})()

        value, _ = _session_read_modbus(Client(), "12")
        assert value == 42
        assert seen == {"address": 12, "device_id": 7}
