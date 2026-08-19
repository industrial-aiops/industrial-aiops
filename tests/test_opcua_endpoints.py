"""GetEndpoints without a session — the OPC-UA identification a scan may make.

Two properties carry the whole point and are each pinned:

* **No session is created.** ``server_info`` consumes one of the server's session
  slots, and embedded servers commonly allow two to five — an unattended re-scan
  can evict the plant's real SCADA client from its own PLC. The fake client here
  raises if ``connect()`` is ever called.
* **The ThreadLoop is always torn down.** asyncua's sync Client starts a
  NON-DAEMON thread in its constructor; skipping ``disconnect`` leaks one per
  probe and a long-lived scanner never exits. Asserted on both the success and
  the failure path, because the failure path is the one that leaks in practice.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.opcua import ops
from iaiops.core.runtime import connection
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import OTConnectionError

pytestmark = pytest.mark.unit


class FakeLocalizedText:
    def __init__(self, text: str) -> None:
        self.Text = text


class FakeAppDescription:
    def __init__(self, name="", uri="", product=""):
        self.ApplicationName = FakeLocalizedText(name)
        self.ApplicationUri = uri
        self.ProductUri = product


class FakeTokenPolicy:
    def __init__(self, token_type: int) -> None:
        self.TokenType = token_type


class FakeEndpoint:
    def __init__(
        self,
        url="opc.tcp://plc:4840",
        policy="http://opcfoundation.org/UA/SecurityPolicy#Basic256Sha256",
        mode=3,
        level=3,
        tokens=(1,),
        server=None,
    ):
        self.EndpointUrl = url
        self.SecurityPolicyUri = policy
        self.SecurityMode = mode
        self.SecurityLevel = level
        self.UserIdentityTokens = [FakeTokenPolicy(t) for t in tokens]
        self.Server = server or FakeAppDescription("Plant PLC", "urn:plc", "urn:vendor:prod")


class FakeClient:
    """Records what was called. connect() is a failure, not a fallback."""

    def __init__(self, endpoints=None, raise_on_endpoints=None):
        self.endpoints = endpoints if endpoints is not None else [FakeEndpoint()]
        self.raise_on_endpoints = raise_on_endpoints
        self.disconnected = 0
        self.session_opened = False

    def connect(self):  # pragma: no cover — must never run
        self.session_opened = True
        raise AssertionError("identification opened a SESSION — that costs a session slot")

    def connect_and_get_server_endpoints(self):
        if self.raise_on_endpoints:
            raise self.raise_on_endpoints
        return self.endpoints

    def disconnect(self):
        self.disconnected += 1


@pytest.fixture
def target():
    return TargetConfig(
        name="plc1", protocol="opcua", endpoint_url="opc.tcp://10.0.0.5:4840", timeout_s=2
    )


def use_client(monkeypatch, client):
    monkeypatch.setattr(connection, "_build_opcua_client", lambda _t: client)
    return client


class TestNoSessionIsCreated:
    def test_identification_never_opens_a_session(self, monkeypatch, target):
        client = use_client(monkeypatch, FakeClient())
        ops.opcua_endpoints(target)
        assert client.session_opened is False

    def test_it_uses_the_session_free_call(self, monkeypatch, target):
        """If a refactor routed this through opcua_session, the fake's connect()
        would fire and this test would say so in one line."""
        use_client(monkeypatch, FakeClient())
        result = ops.opcua_endpoints(target)
        assert result["endpoint_count"] == 1


class TestThreadLoopIsAlwaysReleased:
    def test_released_on_success(self, monkeypatch, target):
        client = use_client(monkeypatch, FakeClient())
        ops.opcua_endpoints(target)
        assert client.disconnected == 1

    def test_released_on_failure(self, monkeypatch, target):
        """The failure path is the one that leaks in practice — a dead endpoint
        would otherwise leave a non-daemon thread per probe and a scanner that
        never exits."""
        client = use_client(
            monkeypatch, FakeClient(raise_on_endpoints=OSError("connection refused"))
        )
        with pytest.raises(OTConnectionError):
            ops.opcua_endpoints(target)
        assert client.disconnected == 1

    def test_a_failing_disconnect_does_not_mask_the_real_error(self, monkeypatch, target):
        class RudeClient(FakeClient):
            def disconnect(self):
                super().disconnect()
                raise OSError("teardown blew up")

        use_client(monkeypatch, RudeClient(raise_on_endpoints=OSError("refused")))
        with pytest.raises(OTConnectionError, match="GetEndpoints"):
            ops.opcua_endpoints(target)


class TestIdentificationContent:
    def test_application_identity_is_extracted(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient())
        result = ops.opcua_endpoints(target)
        assert result["application_name"] == "Plant PLC"
        assert result["application_uri"] == "urn:plc"
        assert result["product_uri"] == "urn:vendor:prod"

    def test_policy_uris_are_shortened_to_their_fragment(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient())
        assert ops.opcua_endpoints(target)["endpoints"][0]["security_policy"] == "Basic256Sha256"

    def test_security_mode_is_named_not_numeric(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient([FakeEndpoint(mode=2)]))
        assert ops.opcua_endpoints(target)["endpoints"][0]["security_mode"] == "Sign"

    def test_user_token_types_are_named(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient([FakeEndpoint(tokens=(0, 1, 2))]))
        tokens = ops.opcua_endpoints(target)["endpoints"][0]["user_tokens"]
        assert tokens == ["Anonymous", "UserName", "Certificate"]

    def test_an_unknown_enum_value_is_kept_visible_not_dropped(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient([FakeEndpoint(mode=99, tokens=(77,))]))
        row = ops.opcua_endpoints(target)["endpoints"][0]
        assert row["security_mode"] == "mode_99"
        assert row["user_tokens"] == ["token_77"]


class TestSecurityFindings:
    def test_none_security_is_surfaced_as_a_boolean(self, monkeypatch, target):
        """'Still offers SecurityPolicy None' is a finding a 62443 review acts on,
        and it is visible here without authenticating."""
        use_client(
            monkeypatch,
            FakeClient(
                [
                    FakeEndpoint(
                        policy="http://opcfoundation.org/UA/SecurityPolicy#None",
                        mode=1,
                        tokens=(0,),
                    )
                ]
            ),
        )
        result = ops.opcua_endpoints(target)
        assert result["allows_none_security"] is True
        assert result["allows_anonymous"] is True

    def test_a_hardened_server_reports_neither(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient([FakeEndpoint(mode=3, tokens=(2,))]))
        result = ops.opcua_endpoints(target)
        assert result["allows_none_security"] is False
        assert result["allows_anonymous"] is False

    def test_a_mixed_server_is_flagged_on_the_weakest_endpoint(self, monkeypatch, target):
        """One insecure endpoint is enough — an attacker picks it, so the report
        must not average it away."""
        use_client(
            monkeypatch,
            FakeClient(
                [
                    FakeEndpoint(mode=3, tokens=(2,)),
                    FakeEndpoint(
                        policy="http://opcfoundation.org/UA/SecurityPolicy#None",
                        mode=1,
                        tokens=(0,),
                    ),
                ]
            ),
        )
        result = ops.opcua_endpoints(target)
        assert result["endpoint_count"] == 2
        assert result["allows_none_security"] is True


class TestDegradation:
    def test_a_server_returning_no_endpoints_is_not_an_error(self, monkeypatch, target):
        """Answering GetEndpoints with an empty list is odd but real; it means
        identified-as-OPC-UA and nothing more, not a crash and not an invented name."""
        use_client(monkeypatch, FakeClient([]))
        result = ops.opcua_endpoints(target)
        assert result["endpoint_count"] == 0
        assert result["application_name"] == ""
        assert result["allows_none_security"] is False

    def test_missing_attributes_do_not_raise(self, monkeypatch, target):
        class Sparse:
            EndpointUrl = "opc.tcp://x:4840"

        use_client(monkeypatch, FakeClient([Sparse()]))
        row = ops.opcua_endpoints(target)["endpoints"][0]
        assert row["security_mode"] == "Invalid"
        assert row["user_tokens"] == []

    def test_a_failed_channel_teaches_what_to_check(self, monkeypatch, target):
        use_client(monkeypatch, FakeClient(raise_on_endpoints=OSError("timed out")))
        with pytest.raises(OTConnectionError) as excinfo:
            ops.opcua_endpoints(target)
        message = str(excinfo.value)
        assert "endpoint_url" in message and "certificate" in message
