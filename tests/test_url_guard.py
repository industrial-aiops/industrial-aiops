"""Outbound base-URL egress guard tests — stored-token exfiltration defense.

The guard is pure (no sockets): it must refuse sending a stored secret to any
destination that is neither clearly internal nor operator-allowlisted via
``IAIOPS_TOKEN_EGRESS_HOSTS``, and must always refuse non-http(s) schemes and
URLs that embed credentials — BEFORE any network I/O happens.
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.url_guard import (
    TOKEN_EGRESS_HOSTS_ENV,
    UrlEgressError,
    validate_base_url,
)


def _check(url: str, *, token: bool = True) -> str:
    return validate_base_url(url, connector="Test connector", token_attached=token)


# ───────────────────────────────────────────────── scheme / shape (always on)
@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    ["ftp://bms/api", "file:///etc/passwd", "javascript:alert(1)", "bms/api", ""],
)
def test_non_http_schemes_refused_even_without_token(url):
    with pytest.raises(UrlEgressError, match="http"):
        _check(url, token=False)


@pytest.mark.unit
@pytest.mark.parametrize("token", [True, False])
def test_userinfo_in_url_refused(token):
    with pytest.raises(UrlEgressError, match="credentials"):
        _check("https://alice:hunter2@bms/api", token=token)


@pytest.mark.unit
def test_missing_host_refused():
    with pytest.raises(UrlEgressError, match="no host"):
        _check("https:///api", token=False)


@pytest.mark.unit
def test_unparseable_port_refused():
    with pytest.raises(UrlEgressError, match="port"):
        _check("https://bms:99999/api")


# ───────────────────────────────────────────── host policy (token attached)
@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://bms/api",  # single-label hostname
        "https://localhost:8043",
        "https://127.0.0.1/api",
        "http://10.20.30.40:8080/api",
        "https://192.168.1.5/api",
        "https://[::1]:8043/api",
        "https://[fd00::5]/api",
        "https://bms.local/api",
        "https://gw.plant.internal/api",
        "https://scada.lan/api",
    ],
)
def test_internal_destinations_allowed_with_token(url, monkeypatch):
    monkeypatch.delenv(TOKEN_EGRESS_HOSTS_ENV, raising=False)
    assert _check(url) == url


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example.com/api",
        "https://8.8.8.8/api",
        "http://evil.io",
        "https://bms.example.com./api",  # trailing-dot FQDN normalizes to public
    ],
)
def test_public_destinations_refused_with_token(url, monkeypatch):
    monkeypatch.delenv(TOKEN_EGRESS_HOSTS_ENV, raising=False)
    with pytest.raises(UrlEgressError, match=TOKEN_EGRESS_HOSTS_ENV):
        _check(url)


@pytest.mark.unit
def test_public_destination_allowed_without_token(monkeypatch):
    monkeypatch.delenv(TOKEN_EGRESS_HOSTS_ENV, raising=False)
    assert _check("https://status.example.com/api", token=False)


# ─────────────────────────────────────────── operator allowlist (additive)
@pytest.mark.unit
def test_env_allowlist_permits_exact_host(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "bms.acme.example, other.example")
    assert _check("https://bms.acme.example/api")


@pytest.mark.unit
def test_env_allowlist_is_case_insensitive(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "BMS.Acme.Example")
    assert _check("https://bms.ACME.example/api")


@pytest.mark.unit
def test_env_allowlist_wildcard_matches_subdomains_only(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "*.acme.example")
    assert _check("https://gw1.acme.example:8043/api")
    with pytest.raises(UrlEgressError):
        _check("https://acme.example/api")  # apex is NOT covered by the wildcard
    with pytest.raises(UrlEgressError):
        _check("https://notacme.example/api")


@pytest.mark.unit
def test_env_allowlist_port_entry_requires_port_match(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "gw.acme.example:8043")
    assert _check("https://gw.acme.example:8043/api")
    with pytest.raises(UrlEgressError):
        _check("https://gw.acme.example:9999/api")
    with pytest.raises(UrlEgressError):
        _check("https://gw.acme.example/api")  # no port given ≠ pinned port


@pytest.mark.unit
def test_env_allowlist_does_not_lock_out_internal_hosts(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "gw.acme.example")
    assert _check("https://bms/api")  # internal defaults stay allowed (additive)


@pytest.mark.unit
def test_unparseable_url_refused():
    with pytest.raises(UrlEgressError, match="not a parseable URL"):
        _check("https://[bad-bracket/api", token=False)


@pytest.mark.unit
def test_malformed_allowlist_entries_never_match(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "gw[bad.example, :8043")
    with pytest.raises(UrlEgressError, match=TOKEN_EGRESS_HOSTS_ENV):
        _check("https://gw.acme.example:8043/api")


@pytest.mark.unit
def test_env_allowlist_never_unlocks_userinfo_or_scheme(monkeypatch):
    monkeypatch.setenv(TOKEN_EGRESS_HOSTS_ENV, "evil.example")
    with pytest.raises(UrlEgressError, match="credentials"):
        _check("https://tok@evil.example/api")
    with pytest.raises(UrlEgressError, match="http"):
        _check("ftp://evil.example/api")
