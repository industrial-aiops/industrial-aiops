"""Account / IP allowlist — defense-in-depth for network-fronted MCP transports.

When iaiops runs over an HTTP/SSE transport (rather than stdio), it may sit **behind a gateway**
that already does account/IP whitelisting (e.g. a FastAPI front). This module is the same guard for
the **standalone** case, and a reusable check a gateway/embedding can call directly.

Pure + injectable: the parse/check logic here has no I/O, so it is fully unit-testable; the HTTP
middleware that applies it lives in ``mcp_server.transport``. CIDR ranges are supported for IPs.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field

# Env config (comma-separated). Empty/unset → that dimension is unrestricted (allow-all).
ACCOUNTS_ENV = "IAIOPS_ALLOWLIST_ACCOUNTS"
IPS_ENV = "IAIOPS_ALLOWLIST_IPS"

_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class Allowlist:
    """An immutable account + IP allowlist. Empty set on a dimension = unrestricted."""

    accounts: frozenset[str] = frozenset()
    ip_networks: tuple[_IPNetwork, ...] = field(default_factory=tuple)

    @property
    def restricts_accounts(self) -> bool:
        return bool(self.accounts)

    @property
    def restricts_ips(self) -> bool:
        return bool(self.ip_networks)

    def account_allowed(self, account: str | None) -> bool:
        """True if ``account`` passes (or no account allowlist is configured)."""
        if not self.accounts:
            return True
        return (account or "").strip() in self.accounts

    def ip_allowed(self, ip: str | None) -> bool:
        """True if ``ip`` falls in an allowed network (or no IP allowlist is configured)."""
        if not self.ip_networks:
            return True
        try:
            addr = ipaddress.ip_address((ip or "").strip())
        except ValueError:
            return False  # unparseable client address is never allowed under an IP allowlist
        return any(addr in net for net in self.ip_networks)


def _split(value: str | None) -> list[str]:
    return [tok.strip() for tok in (value or "").split(",") if tok.strip()]


def parse_allowlist(accounts: list[str] | None, ips: list[str] | None) -> Allowlist:
    """Build an ``Allowlist`` from account names + IP/CIDR strings (invalid IPs are skipped)."""
    nets: list[_IPNetwork] = []
    for token in ips or []:
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            continue  # skip malformed entries rather than fail the whole server startup
    return Allowlist(accounts=frozenset(accounts or []), ip_networks=tuple(nets))


def load_allowlist_env() -> Allowlist:
    """Load the allowlist from ``IAIOPS_ALLOWLIST_ACCOUNTS`` / ``IAIOPS_ALLOWLIST_IPS``."""
    return parse_allowlist(_split(os.environ.get(ACCOUNTS_ENV)), _split(os.environ.get(IPS_ENV)))


__all__ = ["Allowlist", "parse_allowlist", "load_allowlist_env", "ACCOUNTS_ENV", "IPS_ENV"]
