"""L1 — the gentle TCP sweep. The first code here that puts a packet on a wire.

What it does is deliberately the least a scanner can do and still learn
something: for each allowlisted port, one ordinary TCP connect, then an
immediate orderly close. No payload is sent. There is no raw socket, no
half-open SYN, no ICMP, and no retry storm — a full handshake from the kernel's
own stack is what any client would do, and it is the one thing a device cannot
mistake for an attack.

The verdict per port is three-valued, and the distinction is the point:

* ``open`` — something is listening.
* ``refused`` — the host is **alive** and simply is not running that service.
  This is a positive finding about the host, not an absence.
* ``filtered`` — the connect timed out. Usually an ACL silently dropping, but it
  could equally be a device too busy to answer.

Collapsing the last two into "closed" is where a scan report starts lying to the
person holding it, so they never merge. A host that only ever refuses is
reported as alive with no industrial services — which is exactly the answer
"is anything here?" deserves.
"""

from __future__ import annotations

import errno
import socket
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from iaiops.core.discovery import wirelog
from iaiops.core.discovery.pacing import HostBackedOff, Pacer, SegmentUnhealthy, shuffled
from iaiops.core.discovery.types import (
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    HostResult,
    PacingPolicy,
    PortResult,
)

#: Errno values that prove the host answered — it is up, the port is shut.
_REFUSED_ERRNOS = frozenset({errno.ECONNREFUSED, errno.ECONNRESET})

#: Errno values that mean the network, not the host, said no. Distinct from a
#: timeout: a hard unreachable is a routing/ACL answer we can quote exactly.
_UNREACHABLE_ERRNOS = frozenset(
    {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN}
)


@dataclass(frozen=True)
class ProbeOutcome:
    """One (host, port) verdict, plus what to tell the wire log and health."""

    host: str
    port: int
    state: str
    rtt_ms: float | None
    error: str = ""

    @property
    def proves_host_alive(self) -> bool:
        return self.state in (PORT_OPEN, PORT_REFUSED)


def probe_port(
    host: str,
    port: int,
    *,
    timeout_s: float,
    connector: Callable[..., socket.socket] = socket.create_connection,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProbeOutcome:
    """One TCP connect and immediate close. Never raises for a network condition.

    ``connector`` is injected so the sweep can be driven against a fake in tests
    without monkeypatching the socket module globally.
    """
    started = monotonic()
    try:
        sock = connector((host, port), timeout_s)
    except TimeoutError:
        return ProbeOutcome(host, port, PORT_FILTERED, None, "timeout")
    except OSError as exc:
        elapsed = (monotonic() - started) * 1000.0
        code = exc.errno
        if code in _REFUSED_ERRNOS:
            return ProbeOutcome(host, port, PORT_REFUSED, round(elapsed, 2), "refused")
        if code in _UNREACHABLE_ERRNOS:
            # A router answered on the host's behalf. The host itself said
            # nothing, so this is not evidence it is alive.
            return ProbeOutcome(
                host, port, PORT_FILTERED, round(elapsed, 2), f"unreachable ({exc.strerror})"
            )
        # socket.timeout is an OSError subclass on some paths; treat any
        # remaining error as filtered rather than inventing a verdict.
        return ProbeOutcome(
            host, port, PORT_FILTERED, None, f"{type(exc).__name__}: {exc.strerror or exc}"
        )

    elapsed = (monotonic() - started) * 1000.0
    try:
        # Orderly shutdown before close: tell the peer we are done rather than
        # leaving it to time out a half-open connection. Some embedded stacks
        # hold a connection slot until they see the FIN.
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed by the peer — nothing to be done, nothing wrong
    finally:
        sock.close()
    return ProbeOutcome(host, port, PORT_OPEN, round(elapsed, 2))


def sweep_hosts(
    hosts: Iterable[str],
    ports: Sequence[int],
    *,
    pacing: PacingPolicy | None = None,
    log: wirelog.WireLog | None = None,
    seed: int = 0,
    connector: Callable[..., socket.socket] = socket.create_connection,
) -> tuple[tuple[HostResult, ...], tuple[str, ...], bool]:
    """Sweep ``ports`` on ``hosts``, gently. Returns results, notes, and whether
    the run aborted on an unhealthy segment.

    The abort arrives as a flag rather than only as prose in ``notes``: the
    caller decides a verdict from it, and a verdict that depended on an
    exception's wording would silently go wrong the day someone reworded it.

    Every brake in :class:`~iaiops.core.discovery.pacing.Pacer` applies. A host
    that fails repeatedly is dropped for the run; a segment that fails wholesale
    aborts it, and the note says so rather than returning a quiet partial.
    """
    pacing = pacing or PacingPolicy()
    log = log or wirelog.WireLog()
    pacer = Pacer(pacing)
    ordered = shuffled(hosts, seed=seed)
    notes: list[str] = []
    per_host: dict[str, list[PortResult]] = {h: [] for h in ordered}
    per_host_errors: dict[str, list[str]] = {h: [] for h in ordered}
    aborted = False

    def probe_one(host: str, port: int) -> ProbeOutcome | None:
        try:
            with pacer.probe(host):
                outcome = probe_port(
                    host, port, timeout_s=pacing.connect_timeout_s, connector=connector
                )
        except HostBackedOff:
            return None
        log.record(wirelog.TCP_CONNECT, host=host, detail=str(port))
        if outcome.proves_host_alive:
            pacer.health.record_ok(host)
        else:
            pacer.health.record_error(host)
        return outcome

    # Submitted PORT-major, so consecutive tasks are for different hosts. The
    # obvious host-major order queues one host's ports back to back; the host
    # gate then serialises them while they occupy the concurrency budget, and
    # both throughput and the preview's duration estimate go wrong. Spreading
    # each host's ports across the run is also gentler per device than probing
    # six of its ports in a burst.
    with ThreadPoolExecutor(max_workers=pacing.max_concurrency) as pool:
        futures = {
            pool.submit(probe_one, host, port): (host, port) for port in ports for host in ordered
        }
        for future in as_completed(futures):
            host, port = futures[future]
            try:
                outcome = future.result()
            except SegmentUnhealthy as exc:
                aborted = True
                notes.append(str(exc))
                # Cancel INSIDE the executor's context: leaving the block first
                # runs shutdown(wait=True), which drains every queued future
                # before a cancel could ever apply.
                for pending in futures:
                    pending.cancel()
                break
            except Exception as exc:  # noqa: BLE001 — one odd probe must not end the run
                per_host_errors[host].append(f"{port}: {type(exc).__name__}: {exc}")
                continue
            if outcome is None:
                continue
            per_host[host].append(
                PortResult(port=outcome.port, state=outcome.state, rtt_ms=outcome.rtt_ms)
            )
            if outcome.error and outcome.state == PORT_FILTERED:
                per_host_errors[host].append(f"{port}: {outcome.error}")

    blocked = pacer.health.blocked_hosts
    for host in blocked:
        if host in per_host_errors:
            # Recorded PER HOST, not only as a run-level note. A dropped host has
            # fewer ports in its row than its neighbours, and a report that shows
            # "3 ports checked" next to "6 ports checked" without saying why
            # looks like the scan is inconsistent rather than careful.
            per_host_errors[host].append(
                "dropped after repeated failures — its remaining allowlisted ports "
                "were NOT probed, so this row is incomplete by design"
            )
    if blocked:
        notes.append(
            f"{len(blocked)} host(s) dropped after repeated failures and not probed "
            f"further: {', '.join(blocked[:10])}" + (" …" if len(blocked) > 10 else "")
        )

    results = tuple(
        HostResult(
            ip=host,
            sources=("tcp",),
            ports=tuple(sorted(per_host[host], key=lambda p: p.port)),
            errors=tuple(per_host_errors[host][:20]),
        )
        for host in ordered
        if per_host[host] or per_host_errors[host]
    )
    return results, tuple(notes), aborted


def diagnose_empty_sweep(results: Sequence[HostResult]) -> tuple[str, ...]:
    """Explain a sweep that found nothing. Never return a silent empty list.

    The two failure modes look identical in a summary and are completely
    different to act on, so they are always separated: every port timing out
    points at a firewall or the wrong VLAN, whereas refusals mean the hosts are
    right there and are not answering on **the ports this scan tried**.

    That last qualifier is the whole correctness of this function. The port set
    is a fixed allowlist and ``--protocols`` may only narrow it, never widen it
    — which is a safety property worth keeping, and exactly why a refusal on
    those ports cannot be reported as a fact about what the host speaks. Found
    by scanning a lab host whose Modbus server listens on 15020: the note said
    it was "not running any protocol this tool speaks", and ``iaiops modbus
    holding`` read its registers on the same box a minute later.
    """
    if any(h.protocols for h in results):
        return ()

    alive = [h for h in results if h.alive]
    filtered_only = [h for h in results if h.ports and not h.alive]

    notes: list[str] = []
    if not results:
        notes.append(
            "No host produced any response at all. Check that this machine is on the "
            "intended VLAN and that the CIDR is the one you meant — a mistyped prefix "
            "is the most common cause of a completely silent sweep."
        )
        return tuple(notes)

    if alive:
        tried = sorted({port.port for host in alive for port in host.ports})
        ports = ", ".join(str(port) for port in tried) if tried else "none"
        notes.append(
            f"{len(alive)} host(s) are ALIVE but refused every port this scan tried "
            f"({ports}). They are there and are not answering industrial protocols "
            "on THOSE ports — which is not the same as not speaking them. The port "
            "set is a fixed allowlist and is never widened, so a device on a "
            "non-standard port is invisible here. If you expect one, give it an "
            "endpoint in config.yaml and read it directly."
        )
    if filtered_only:
        notes.append(
            f"{len(filtered_only)} host(s) timed out on every port with no refusal. "
            "A silent drop usually means a firewall or ACL between here and them, "
            "not an absent device — the same result an offline host would give, which "
            "is why the two are reported separately."
        )
    return tuple(notes)


__all__ = [
    "ProbeOutcome",
    "probe_port",
    "sweep_hosts",
    "diagnose_empty_sweep",
]
