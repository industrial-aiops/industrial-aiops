"""SIEM-forwarding hardening tests (M-5): https default, plaintext warnings,
bearer-token auth."""

from __future__ import annotations

import urllib.request

import pytest

from iaiops.core.governance.forward import HttpSink, SyslogUDPSink, _http_url


@pytest.mark.unit
def test_bare_host_defaults_to_https():
    assert _http_url("siem.example.com", 0, "/") == "https://siem.example.com:443/"


@pytest.mark.unit
def test_explicit_http_still_accepted_with_warning(caplog):
    url = _http_url("http://siem.example.com", 0, "/ingest")
    assert url == "http://siem.example.com:80/ingest"
    with caplog.at_level("WARNING", logger="iaiops.audit.forward"):
        HttpSink(url)
    assert any("PLAINTEXT" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_https_sink_no_plaintext_warning(caplog):
    with caplog.at_level("WARNING", logger="iaiops.audit.forward"):
        HttpSink("https://siem.example.com:443/")
    assert not any("PLAINTEXT" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_syslog_udp_warns_plaintext(caplog):
    with caplog.at_level("WARNING", logger="iaiops.audit.forward"):
        sink = SyslogUDPSink("collector.example.com")
    sink.close()
    assert any("PLAINTEXT" in rec.message for rec in caplog.records)


class _CapturingOpener:
    def __init__(self) -> None:
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp()


@pytest.mark.unit
def test_bearer_token_header_from_env(monkeypatch):
    monkeypatch.setenv("IAIOPS_FORWARD_TOKEN", "s3cr3t")
    opener = _CapturingOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    sink = HttpSink("https://siem.example.com/ingest")
    sink.send('{"id": 1}')
    assert opener.requests[0].get_header("Authorization") == "Bearer s3cr3t"


@pytest.mark.unit
def test_no_auth_header_without_token(monkeypatch):
    monkeypatch.delenv("IAIOPS_FORWARD_TOKEN", raising=False)
    opener = _CapturingOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    sink = HttpSink("https://siem.example.com/ingest")
    sink.send('{"id": 1}')
    assert opener.requests[0].get_header("Authorization") is None


@pytest.mark.unit
def test_custom_auth_scheme_splunk_hec(monkeypatch):
    monkeypatch.setenv("IAIOPS_FORWARD_TOKEN", "hec-token")
    monkeypatch.setenv("IAIOPS_FORWARD_AUTH_SCHEME", "Splunk")
    opener = _CapturingOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    HttpSink("https://siem.example.com/ingest").send('{"id": 1}')
    assert opener.requests[0].get_header("Authorization") == "Splunk hec-token"


@pytest.mark.unit
def test_custom_auth_header_raw_api_key(monkeypatch):
    monkeypatch.setenv("IAIOPS_FORWARD_TOKEN", "raw-key")
    monkeypatch.setenv("IAIOPS_FORWARD_AUTH_HEADER", "X-Api-Key")
    monkeypatch.setenv("IAIOPS_FORWARD_AUTH_SCHEME", "")  # raw value, no scheme prefix
    opener = _CapturingOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    HttpSink("https://siem.example.com/ingest").send('{"id": 1}')
    request = opener.requests[0]
    assert request.get_header("X-api-key") == "raw-key"
    assert request.get_header("Authorization") is None


@pytest.mark.unit
def test_constructor_args_override_env(monkeypatch):
    monkeypatch.setenv("IAIOPS_FORWARD_AUTH_SCHEME", "Splunk")
    opener = _CapturingOpener()
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    HttpSink("https://x.example.com/", token="t", auth_scheme="ApiKey").send("{}")
    assert opener.requests[0].get_header("Authorization") == "ApiKey t"
