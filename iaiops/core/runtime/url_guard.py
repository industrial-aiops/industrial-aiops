"""Outbound base-URL guard — blocks stored-token exfiltration via caller URLs.

The HTTP-layer connectors (BAS controller, Gateway read layer) accept a
caller-supplied ``base_url`` AND a ``secret_name`` resolved from the encrypted
secret store, then attach ``Authorization: Bearer <token>``. Without a
destination check, a prompt-injected or malicious caller could point
``base_url`` at an attacker-controlled host and exfiltrate the stored token in
a single tool call. This guard closes that hole, BEFORE any network I/O:

- The scheme must be ``http``/``https`` and the URL must not embed credentials
  (``user:pass@host``) — enforced always, token or not.
- When a stored token WILL be attached, the destination must be clearly
  internal — a private/loopback/link-local literal IP, ``localhost``, a
  single-label hostname (``https://bms``) or a ``.local`` / ``.lan`` /
  ``.internal`` / ``.home.arpa`` name — OR match the operator's
  ``IAIOPS_TOKEN_EGRESS_HOSTS`` allowlist (comma-separated ``host``,
  ``host:port`` or ``*.suffix`` entries; additive to the internal defaults).
- Requests without a stored token skip the host policy (nothing to exfiltrate)
  but still get the scheme/userinfo checks.

Pure functions, no sockets, no DNS: the policy judges the URL as written, so it
cannot be bypassed by resolution tricks and is trivially unit-testable.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import SplitResult, urlsplit

TOKEN_EGRESS_HOSTS_ENV = "IAIOPS_TOKEN_EGRESS_HOSTS"  # nosec B105 — env var name, not a secret

_ALLOWED_SCHEMES = frozenset({"http", "https"})
# Hostname suffixes that never resolve on the public internet (mDNS, RFC 8375
# home networks, and the conventional private-DNS zones).
_INTERNAL_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localhost")


class UrlEgressError(ValueError):
    """A caller-supplied base URL failed the outbound-egress policy."""


def load_token_egress_hosts() -> tuple[str, ...]:
    """Operator allowlist from ``IAIOPS_TOKEN_EGRESS_HOSTS`` (lowercased, trimmed)."""
    raw = os.environ.get(TOKEN_EGRESS_HOSTS_ENV, "")
    return tuple(entry.strip().lower() for entry in raw.split(",") if entry.strip())


def _entry_host_port(entry: str) -> tuple[str, int | None]:
    """Split one allowlist entry into (host, port|None); ('' , None) if unparseable."""
    try:
        parts = urlsplit(f"//{entry}")
        return ((parts.hostname or "").strip("."), parts.port)
    except ValueError:
        return ("", None)


def _entry_matches(host: str, port: int | None, entry: str) -> bool:
    """True if ``host``(+``port``) matches one allowlist entry (``*.suffix`` ok)."""
    entry_host, entry_port = _entry_host_port(entry)
    if not entry_host:
        return False
    if entry_port is not None and port != entry_port:
        return False
    if entry_host.startswith("*."):
        return host.endswith(entry_host[1:])  # '*.acme.com' → any '<sub>.acme.com'
    return host == entry_host


def _is_internal_host(host: str) -> bool:
    """True for destinations that cannot be a public internet host as written."""
    try:
        # Covers loopback, RFC 1918, link-local, and IPv6 unique-local literals.
        return ipaddress.ip_address(host).is_private
    except ValueError:
        pass  # not a literal IP — judge the hostname shape
    if host == "localhost" or "." not in host:
        return True
    return host.endswith(_INTERNAL_SUFFIXES)


def _split_url(url: str, connector: str) -> SplitResult:
    """Parse ``url``, translating a parser error into a teaching refusal."""
    try:
        return urlsplit(url)
    except ValueError as exc:
        raise UrlEgressError(
            f"{connector} base_url {url!r} is not a parseable URL: {exc}."
        ) from exc


def _port_of(parts: SplitResult, url: str, connector: str) -> int | None:
    """Extract the port, refusing URLs whose port is unparseable/out-of-range."""
    try:
        return parts.port
    except ValueError as exc:
        raise UrlEgressError(
            f"{connector} base_url {url!r} has an invalid port. Use a numeric "
            f"port in 1..65535, e.g. 'https://<host>:8043'."
        ) from exc


def validate_base_url(base_url: str, *, connector: str, token_attached: bool) -> str:
    """Validate a caller-supplied base URL against the outbound-egress policy.

    Args:
        base_url: The URL exactly as the tool caller supplied it.
        connector: Display name used in teaching errors (e.g. 'BAS controller').
        token_attached: True when a stored secret WILL ride on the request —
            this switches on the destination-host policy.

    Returns the stripped URL. Raises :class:`UrlEgressError` when refused;
    nothing has touched the network at that point.
    """
    url = str(base_url or "").strip()
    parts = _split_url(url, connector)
    if (parts.scheme or "").lower() not in _ALLOWED_SCHEMES:
        raise UrlEgressError(
            f"{connector} base_url must be an http(s) URL, got {url!r}. "
            f"Pass e.g. 'https://<host>/api'."
        )
    if parts.username is not None or parts.password is not None:
        raise UrlEgressError(
            f"{connector} base_url {url!r} embeds credentials (user@host). Refused — "
            f"pass credentials via the encrypted secret store (secret_name), "
            f"never inside the URL."
        )
    host = (parts.hostname or "").strip(".").lower()
    if not host:
        raise UrlEgressError(f"{connector} base_url {url!r} has no host.")
    port = _port_of(parts, url, connector)
    if not token_attached or _is_internal_host(host):
        return url
    allowlist = load_token_egress_hosts()
    if any(_entry_matches(host, port, entry) for entry in allowlist):
        return url
    raise UrlEgressError(
        f"Refused to send the stored secret to '{host}': stored tokens only go "
        f"to internal destinations (private/loopback IPs, single-label hosts, "
        f".local/.lan/.internal/.home.arpa names) or hosts the operator listed "
        f"in {TOKEN_EGRESS_HOSTS_ENV} (comma-separated host / host:port / "
        f"*.suffix entries). This blocks token exfiltration via a "
        f"caller-supplied base_url; no request was sent."
    )


__all__ = [
    "TOKEN_EGRESS_HOSTS_ENV",
    "UrlEgressError",
    "load_token_egress_hosts",
    "validate_base_url",
]
