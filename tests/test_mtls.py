"""Mutual-TLS / certificate-auth wiring for OPC-UA + MQTT.

The client builders are monkeypatched (fake Client classes recording their calls),
so these assert that certificate/TLS config is applied WITHOUT a live server — and
that the no-cert path stays anonymous (back-compat).
"""

from __future__ import annotations

import pytest

import iaiops.core.runtime.connection as conn
from iaiops.core.runtime.config import TargetConfig


class _FakeOpcuaClient:
    def __init__(self, url):
        self.url = url
        self.calls: dict = {}

    def set_user(self, u):
        self.calls["user"] = u

    def set_password(self, p):
        self.calls["pw"] = p

    def set_security_string(self, s):
        self.calls["sec"] = s


@pytest.fixture
def fake_opcua(monkeypatch):
    sync = pytest.importorskip("asyncua.sync")
    created: list[_FakeOpcuaClient] = []

    def _factory(url):
        c = _FakeOpcuaClient(url)
        created.append(c)
        return c

    monkeypatch.setattr(sync, "Client", _factory)
    return created


@pytest.mark.unit
def test_opcua_cert_security_applied(fake_opcua):
    t = TargetConfig(
        name="p", protocol="opcua", endpoint_url="opc.tcp://x:4840",
        security_policy="Basic256Sha256", security_mode="SignAndEncrypt",
        client_cert="/etc/iaiops/c.der", client_key="/etc/iaiops/k.pem",
        server_cert="/etc/iaiops/s.der",
    )
    conn._build_opcua_client(t)
    assert fake_opcua[0].calls["sec"] == (
        "Basic256Sha256,SignAndEncrypt,/etc/iaiops/c.der,/etc/iaiops/k.pem,/etc/iaiops/s.der"
    )


@pytest.mark.unit
def test_opcua_cert_defaults_policy_and_mode(fake_opcua):
    # cert+key present but policy/mode left "None" → sensible secure defaults.
    t = TargetConfig(
        name="p", protocol="opcua", endpoint_url="opc.tcp://x:4840",
        client_cert="/c.der", client_key="/k.pem",
    )
    conn._build_opcua_client(t)
    assert fake_opcua[0].calls["sec"] == "Basic256Sha256,SignAndEncrypt,/c.der,/k.pem"


@pytest.mark.unit
def test_opcua_no_cert_stays_anonymous(fake_opcua):
    t = TargetConfig(name="p", protocol="opcua", endpoint_url="opc.tcp://x:4840")
    conn._build_opcua_client(t)
    assert "sec" not in fake_opcua[0].calls  # back-compat: no security string


class _FakeMqttClient:
    def __init__(self, *a, **k):
        self.calls: dict = {}

    def username_pw_set(self, *a, **k):
        self.calls["auth"] = (a, k)

    def tls_set(self, **k):
        self.calls["tls"] = k


@pytest.fixture
def fake_mqtt(monkeypatch):
    mqtt = pytest.importorskip("paho.mqtt.client")
    created: list[_FakeMqttClient] = []

    class _C(_FakeMqttClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)

    monkeypatch.setattr(mqtt, "Client", _C)
    return created


@pytest.mark.unit
def test_mqtt_client_cert_mutual_auth(fake_mqtt):
    t = TargetConfig(
        name="b", protocol="mqtt", host="broker", use_tls=True,
        ca_cert="/ca.pem", client_cert="/c.pem", client_key="/k.pem",
    )
    conn._build_mqtt_client(t)
    assert fake_mqtt[0].calls["tls"] == {
        "ca_certs": "/ca.pem", "certfile": "/c.pem", "keyfile": "/k.pem",
    }


@pytest.mark.unit
def test_mqtt_certs_enable_tls_without_use_tls_flag(fake_mqtt):
    # Providing certs implies TLS even if use_tls wasn't set.
    t = TargetConfig(name="b", protocol="mqtt", host="broker", ca_cert="/ca.pem")
    conn._build_mqtt_client(t)
    assert fake_mqtt[0].calls["tls"] == {"ca_certs": "/ca.pem"}


@pytest.mark.unit
def test_mqtt_plain_tls_uses_system_store(fake_mqtt):
    t = TargetConfig(name="b", protocol="mqtt", host="broker", use_tls=True)
    conn._build_mqtt_client(t)
    assert fake_mqtt[0].calls["tls"] == {}  # system trust store, unchanged


@pytest.mark.unit
def test_mqtt_no_tls_no_certs(fake_mqtt):
    t = TargetConfig(name="b", protocol="mqtt", host="broker")
    conn._build_mqtt_client(t)
    assert "tls" not in fake_mqtt[0].calls


@pytest.mark.unit
def test_config_parses_cert_paths_and_aliases():
    from iaiops.core.runtime.config import _parse_target

    t = _parse_target({
        "name": "p", "protocol": "opcua", "endpoint_url": "opc.tcp://x:4840",
        "ca_certs": "/ca.pem", "certfile": "/c.pem", "keyfile": "/k.pem",
        "server_cert": "/s.der",
    })
    assert (t.ca_cert, t.client_cert, t.client_key, t.server_cert) == (
        "/ca.pem", "/c.pem", "/k.pem", "/s.der",
    )
