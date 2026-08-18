"""L0 passive — what can be learned without putting anything on the wire.

The kernel already knows some of the answer. Every host this machine has spoken
to recently sits in the ARP/neighbour cache, and reading it costs exactly zero
packets. On a network nobody has authorised you to touch yet, this is the only
honest first move, and it is the whole content of the ``passive`` profile.

Two details decide whether the zero-emission claim is true:

* **``arp -n``, never ``arp -a``.** Without ``-n`` the BSD/macOS tool reverse-
  resolves every address it prints, which puts a DNS query on the network for
  each entry. That would make "emits nothing" false in the one profile whose
  entire purpose is to be true. On Linux the file is read directly and the
  question does not arise.
* **``(incomplete)`` entries are dropped.** An incomplete entry is an ARP
  request that went *unanswered* — the precise opposite of evidence that a host
  exists. Keeping them would populate an inventory with addresses nothing
  replied from.

MAC addresses are normalized, because the same NIC is printed differently by
different kernels: Linux writes ``48:21:0b:33:57:94`` and macOS writes
``48:21:b:33:57:94``. Left alone, one device becomes two assets the moment a
survey is run from a different laptop.
"""

from __future__ import annotations

import platform
import re
import subprocess  # nosec B404 — reads the local kernel ARP cache; see _run
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from iaiops.core.discovery.types import HostResult

#: Linux exposes the cache as a file. Reading it emits nothing, full stop.
PROC_ARP: Final = Path("/proc/net/arp")

#: NUD/ATF flags. 0x0 means the entry is incomplete: the request was never
#: answered, so it is not evidence of a host.
_ATF_COM: Final = 0x2

#: BSD/macOS: ``? (10.0.0.5) at 0:c:29:1a:2b:3c on en0 ifscope [ethernet]``
_BSD_LINE: Final = re.compile(
    r"\((?P<ip>[0-9.]+)\)\s+at\s+(?P<mac>[0-9a-fA-F:]+|\(incomplete\))(?:\s+on\s+(?P<iface>\S+))?"
)

#: Windows: ``  10.0.0.5    00-0c-29-1a-2b-3c   dynamic``
_WIN_LINE: Final = re.compile(
    r"^\s*(?P<ip>[0-9.]+)\s+(?P<mac>[0-9a-fA-F-]{11,17})\s+(?P<kind>\w+)", re.MULTILINE
)

_ARP_TIMEOUT_S: Final = 5.0


@dataclass(frozen=True)
class ARPEntry:
    ip: str
    mac: str
    interface: str = ""


def normalize_mac(raw: str) -> str:
    """Lowercase, colon-separated, zero-padded — or ``""`` if it is not a MAC.

    macOS drops leading zeros from each octet and Windows separates with
    hyphens. Without this, a survey run from a Mac and one run from the plant's
    Linux box disagree about which assets exist.
    """
    text = raw.strip().lower().replace("-", ":")
    if not text or "incomplete" in text:
        return ""
    parts = text.split(":")
    if len(parts) != 6 or not all(p and len(p) <= 2 and _is_hex(p) for p in parts):
        return ""
    mac = ":".join(p.zfill(2) for p in parts)
    if mac == "00:00:00:00:00:00" or not _is_unicast(mac):
        return ""
    return mac


def _is_unicast(mac: str) -> bool:
    """False for broadcast and multicast addresses — neither is a device.

    The subnet broadcast address sits in every ARP cache with
    ``ff:ff:ff:ff:ff:ff``, and IPv4/IPv6 multicast groups sit there as
    ``01:00:5e:…`` / ``33:33:…``. All three share one bit: the least significant
    bit of the first octet. Listing them would put ``192.168.60.255`` in a
    device inventory as though someone could go and find it in a cabinet.
    """
    try:
        first = int(mac.split(":")[0], 16)
    except ValueError:
        return False
    return not first & 0x01


def _is_hex(text: str) -> bool:
    return all(c in "0123456789abcdef" for c in text)


def _run(argv: list[str]) -> str:
    """Run a local read-only command. Fixed argv, no shell, no user input."""
    try:
        proc = subprocess.run(  # nosec B603 — fixed argv, shell=False, no interpolation
            argv,
            capture_output=True,
            text=True,
            timeout=_ARP_TIMEOUT_S,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def _parse_proc_arp(text: str) -> tuple[ARPEntry, ...]:
    entries: list[ARPEntry] = []
    for line in text.splitlines()[1:]:  # first line is the column header
        fields = line.split()
        if len(fields) < 6:
            continue
        ip, _hw_type, flags, mac, _mask, device = fields[:6]
        try:
            complete = int(flags, 16) & _ATF_COM
        except ValueError:
            continue
        normalized = normalize_mac(mac)
        if not complete or not normalized:
            continue
        entries.append(ARPEntry(ip=ip, mac=normalized, interface=device))
    return tuple(entries)


def _parse_bsd_arp(text: str) -> tuple[ARPEntry, ...]:
    entries: list[ARPEntry] = []
    for match in _BSD_LINE.finditer(text):
        mac = normalize_mac(match.group("mac"))
        if not mac:
            continue  # '(incomplete)' — an unanswered request, not a host
        entries.append(
            ARPEntry(ip=match.group("ip"), mac=mac, interface=match.group("iface") or "")
        )
    return tuple(entries)


def _parse_windows_arp(text: str) -> tuple[ARPEntry, ...]:
    entries: list[ARPEntry] = []
    for match in _WIN_LINE.finditer(text):
        mac = normalize_mac(match.group("mac"))
        if not mac:
            continue
        entries.append(ARPEntry(ip=match.group("ip"), mac=mac))
    return tuple(entries)


def read_arp_table(
    *, system: str | None = None, proc_arp: Path | None = None, runner=_run
) -> tuple[tuple[ARPEntry, ...], tuple[str, ...]]:
    """Read the local ARP/neighbour cache. Emits nothing. Never raises.

    Returns ``(entries, notes)``. An unreadable cache is reported in ``notes``
    rather than being returned as an empty table: "nothing is on this network"
    and "I could not look" are different answers, and only one of them is about
    the network.
    """
    system = system or platform.system()
    notes: list[str] = []

    if system == "Linux":
        path = proc_arp or PROC_ARP
        try:
            return _parse_proc_arp(path.read_text(encoding="utf-8")), ()
        except OSError as exc:
            notes.append(f"could not read {path}: {exc}")
            return (), tuple(notes)

    if system in ("Darwin", "FreeBSD", "OpenBSD", "NetBSD"):
        # -n is mandatory: without it this reverse-resolves every address and
        # the 'emits nothing' claim becomes false.
        out = runner(["/usr/sbin/arp", "-an"])
        if not out:
            out = runner(["arp", "-an"])
        if not out:
            notes.append("the arp command produced no output; the local cache could not be read")
        return _parse_bsd_arp(out), tuple(notes)

    if system == "Windows":
        out = runner(["arp", "-a"])
        if not out:
            notes.append("`arp -a` produced no output; the local cache could not be read")
        return _parse_windows_arp(out), tuple(notes)

    notes.append(
        f"passive ARP discovery is not implemented for {system!r}. This is a gap in "
        "this tool on this platform, NOT a statement that the network is empty."
    )
    return (), tuple(notes)


def passive_hosts(
    entries: tuple[ARPEntry, ...], scope: tuple[str, ...] | None = None
) -> tuple[HostResult, ...]:
    """Turn cache entries into hosts, optionally narrowed to the scan scope.

    A host from the cache has a MAC and no ports: it is known to exist and
    nothing is claimed about what it runs. ``HostResult.alive`` is already true
    on the strength of the MAC alone.
    """
    allowed = set(scope) if scope else None
    return tuple(
        HostResult(ip=entry.ip, sources=("arp",), mac=entry.mac)
        for entry in entries
        if allowed is None or entry.ip in allowed
    )


def merge_passive(
    swept: tuple[HostResult, ...], passive: tuple[HostResult, ...]
) -> tuple[HostResult, ...]:
    """Fold cache knowledge into swept results, keyed by IP.

    A host known from both sources carries both provenances, because "the ARP
    cache knew it AND it answered a connect" is a stronger statement than either
    alone — and the report says which.
    """
    by_ip = {h.ip: h for h in passive}
    merged: list[HostResult] = []
    for host in swept:
        known = by_ip.pop(host.ip, None)
        if known is None:
            merged.append(host)
            continue
        sources = tuple(dict.fromkeys(known.sources + host.sources))
        merged.append(
            HostResult(
                ip=host.ip,
                sources=sources,
                mac=host.mac or known.mac,
                ports=host.ports,
                protocols=host.protocols,
                identity=host.identity,
                errors=host.errors,
            )
        )
    merged.extend(by_ip.values())
    return tuple(merged)


__all__ = [
    "ARPEntry",
    "PROC_ARP",
    "normalize_mac",
    "read_arp_table",
    "passive_hosts",
    "merge_passive",
]
