"""Pacing — the machinery that keeps a scan gentle enough to be allowed back.

Four independent brakes, because they fail differently:

* **A global token bucket** caps how fast the whole run touches the network.
* **A concurrency semaphore** caps how many probes are in flight at once.
* **A host gate** allows exactly ONE in-flight probe per host, plus a minimum
  gap between two probes of the same host. Rate limiting alone does not give
  this: twenty connects a second can still be twenty connects to one fragile
  controller.
* **Segment health** counts consecutive failures and pulls the plug. A host that
  times out repeatedly is dropped for the run; a whole segment that does is an
  abort, because the most likely explanation is that we are the problem.

Host ordering is a **seeded shuffle**, not a march up the subnet. Sweeping
10.0.0.1, .2, .3 in order concentrates every connect on one switch's port group
and is what an IDS is tuned to notice; a shuffle spreads the load and stays
reproducible for the report.

The clock and sleep are injectable so the tests exercise real waiting logic
without real waiting.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from iaiops.core.discovery.types import PacingPolicy

#: Token comparison tolerance — see the note in :meth:`TokenBucket.acquire`.
_TOKEN_EPSILON = 1e-9

#: Refill attempts before the limiter declares itself broken instead of spinning.
#: Generous: one round per grant is the normal case, two under contention.
_MAX_REFILL_ROUNDS = 1000


class SegmentUnhealthy(RuntimeError):
    """Raised to abort a run: the segment is failing in a way we may be causing."""


class TokenBucket:
    """Thread-safe token bucket. ``acquire`` blocks and returns seconds waited."""

    def __init__(
        self,
        rate_per_s: float,
        *,
        capacity: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_s <= 0:
            raise ValueError("rate_per_s must be positive")
        self._rate = rate_per_s
        # A one-second burst by default: enough to not stutter, small enough that
        # a burst cannot become a flood.
        self._capacity = capacity if capacity is not None else rate_per_s
        self._tokens = self._capacity
        self._monotonic = monotonic
        self._sleep = sleep
        self._last = monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> float:
        waited = 0.0
        # A refill loop that cannot close its gap must raise, never spin. A hung
        # rate limiter is a hung scanner, and on a plant floor a stuck process is
        # worse than a loud error — the same reason a CI hang is worse than a
        # red test.
        for _ in range(_MAX_REFILL_ROUNDS):
            with self._lock:
                now = self._monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
                self._last = now
                # Compare with a tolerance. Sleeping deficit/rate seconds refills
                # deficit tokens only in exact arithmetic; in floating point it can
                # land a few ulps short, and a strict >= then loops forever on
                # ever-smaller sleeps that never quite close the gap. One
                # nanotoken is meaningless to a rate limiter and it guarantees
                # forward progress.
                if self._tokens + _TOKEN_EPSILON >= tokens:
                    self._tokens = max(0.0, self._tokens - tokens)
                    return waited
                delay = (tokens - self._tokens) / self._rate
            self._sleep(delay)
            waited += delay
        raise RuntimeError(
            f"token bucket failed to grant {tokens} token(s) after "
            f"{_MAX_REFILL_ROUNDS} refill rounds at {self._rate}/s — this is a bug "
            "in the limiter, not a slow network. Refusing to spin."
        )


class HostGate:
    """One in-flight probe per host, and a minimum gap between that host's probes."""

    def __init__(
        self,
        gap_ms: int,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._gap_s = max(0, gap_ms) / 1000.0
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last_finished: dict[str, float] = {}

    def _lock_for(self, host: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(host, threading.Lock())

    @contextmanager
    def hold(self, host: str) -> Iterator[None]:
        host_lock = self._lock_for(host)
        host_lock.acquire()
        try:
            last = self._last_finished.get(host)
            if last is not None:
                remaining = self._gap_s - (self._monotonic() - last)
                if remaining > 0:
                    self._sleep(remaining)
            yield
        finally:
            self._last_finished[host] = self._monotonic()
            host_lock.release()


@dataclass
class SegmentHealth:
    """Consecutive-failure bookkeeping for one host and for the run as a whole."""

    host_backoff_after: int
    segment_abort_after: int
    _host_errors: dict[str, int] = field(default_factory=dict)
    _blocked: set[str] = field(default_factory=set)
    _consecutive: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_ok(self, host: str) -> None:
        with self._lock:
            self._host_errors.pop(host, None)
            self._consecutive = 0

    def record_error(self, host: str) -> None:
        with self._lock:
            count = self._host_errors.get(host, 0) + 1
            self._host_errors[host] = count
            if count >= self.host_backoff_after:
                self._blocked.add(host)
            self._consecutive += 1

    def is_blocked(self, host: str) -> bool:
        with self._lock:
            return host in self._blocked

    @property
    def blocked_hosts(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._blocked))

    def check_segment(self) -> None:
        with self._lock:
            over = self._consecutive >= self.segment_abort_after
        if over:
            raise SegmentUnhealthy(
                f"{self._consecutive} consecutive failures on this segment — aborting. "
                "Either the scope is wrong (check the CIDR and your interface) or this "
                "scan is disturbing the network. Nothing further will be probed."
            )


class Pacer:
    """All four brakes behind one context manager."""

    def __init__(
        self,
        policy: PacingPolicy,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy
        self._bucket = TokenBucket(policy.connects_per_second, monotonic=monotonic, sleep=sleep)
        self._slots = threading.BoundedSemaphore(policy.max_concurrency)
        self._host_gate = HostGate(policy.per_host_gap_ms, monotonic=monotonic, sleep=sleep)
        self.health = SegmentHealth(
            host_backoff_after=policy.host_backoff_after,
            segment_abort_after=policy.segment_abort_after,
        )

    @contextmanager
    def probe(self, host: str) -> Iterator[None]:
        """Hold every brake for the duration of one probe of ``host``.

        Raises :class:`SegmentUnhealthy` if the run has already gone bad, and
        :class:`HostBackedOff` if this host was dropped for the run.
        """
        self.health.check_segment()
        if self.health.is_blocked(host):
            raise HostBackedOff(host)
        self._bucket.acquire()
        self._slots.acquire()
        try:
            with self._host_gate.hold(host):
                yield
        finally:
            self._slots.release()


class HostBackedOff(RuntimeError):
    """This host failed repeatedly and is dropped for the rest of the run."""

    def __init__(self, host: str) -> None:
        super().__init__(f"{host} backed off after repeated failures — not probed again")
        self.host = host


def shuffled(hosts: Iterable[str], seed: int = 0) -> tuple[str, ...]:
    """Deterministically shuffle host order.

    Reproducible (the seed rides in the scan plan and the report) but not
    sequential, so a sweep does not concentrate on one switch's port group.
    """
    items = list(hosts)
    random.Random(seed).shuffle(items)
    return tuple(items)


__all__ = [
    "TokenBucket",
    "HostGate",
    "SegmentHealth",
    "SegmentUnhealthy",
    "HostBackedOff",
    "Pacer",
    "shuffled",
]
