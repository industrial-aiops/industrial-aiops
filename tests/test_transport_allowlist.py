"""Transport selection + account/IP allowlist (pure logic; live HTTP server is 待核实)."""

import pytest

from iaiops.core.governance.allowlist import (
    Allowlist,
    load_allowlist_env,
    parse_allowlist,
)
from mcp_server.transport import TransportError, resolve_transport


# ── transport resolution ──────────────────────────────────────────────────────
@pytest.mark.unit
def test_resolve_transport_default_stdio():
    assert resolve_transport(None) == "stdio"
    assert resolve_transport("") == "stdio"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("stdio", "stdio"),
        ("sse", "sse"),
        ("streamable-http", "streamable-http"),
        ("http", "streamable-http"),
        ("HTTP", "streamable-http"),
        (" SSE ", "sse"),
    ],
)
def test_resolve_transport_aliases(raw, expected):
    assert resolve_transport(raw) == expected


@pytest.mark.unit
def test_resolve_transport_unknown_teaches():
    with pytest.raises(TransportError) as exc:
        resolve_transport("grpc")
    assert "IAIOPS_MCP_TRANSPORT" in str(exc.value)


@pytest.mark.unit
def test_resolve_transport_reads_env(monkeypatch):
    monkeypatch.setenv("IAIOPS_MCP_TRANSPORT", "sse")
    assert resolve_transport() == "sse"


# ── allowlist: accounts ───────────────────────────────────────────────────────
@pytest.mark.unit
def test_account_allowlist_unrestricted_when_empty():
    assert Allowlist().account_allowed("anyone") is True
    assert Allowlist().account_allowed(None) is True


@pytest.mark.unit
def test_account_allowlist_enforced():
    al = parse_allowlist(["alice", "bob"], None)
    assert al.restricts_accounts is True
    assert al.account_allowed("alice") is True
    assert al.account_allowed(" bob ") is True  # trimmed
    assert al.account_allowed("mallory") is False
    assert al.account_allowed(None) is False


# ── allowlist: IPs (incl. CIDR) ───────────────────────────────────────────────
@pytest.mark.unit
def test_ip_allowlist_unrestricted_when_empty():
    assert Allowlist().ip_allowed("203.0.113.9") is True


@pytest.mark.unit
def test_ip_allowlist_single_and_cidr():
    al = parse_allowlist(None, ["10.0.0.5", "192.168.1.0/24"])
    assert al.restricts_ips is True
    assert al.ip_allowed("10.0.0.5") is True
    assert al.ip_allowed("192.168.1.42") is True  # inside CIDR
    assert al.ip_allowed("192.168.2.1") is False  # outside CIDR
    assert al.ip_allowed("10.0.0.6") is False


@pytest.mark.unit
def test_ip_allowlist_unparseable_denied_and_bad_entries_skipped():
    al = parse_allowlist(None, ["not-an-ip", "10.0.0.0/8"])
    assert al.ip_allowed("garbage") is False  # unparseable client IP denied
    assert al.ip_allowed("10.1.2.3") is True  # the one valid CIDR still works
    assert al.ip_allowed(None) is False


@pytest.mark.unit
def test_load_allowlist_env(monkeypatch):
    monkeypatch.setenv("IAIOPS_ALLOWLIST_ACCOUNTS", "svc-a, svc-b")
    monkeypatch.setenv("IAIOPS_ALLOWLIST_IPS", "127.0.0.1, 10.0.0.0/24")
    al = load_allowlist_env()
    assert al.account_allowed("svc-a") and not al.account_allowed("x")
    assert al.ip_allowed("10.0.0.7") and not al.ip_allowed("10.0.1.7")
