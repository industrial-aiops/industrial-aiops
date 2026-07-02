"""OPC-UA transport: client build + error translation (moved from connection.py).

The assembled ``opcua_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_opcua_client``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _build_opcua_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) an asyncua sync Client for ``target``.

    Separated out so tests can monkeypatch this with a fake client factory.
    """
    try:
        from asyncua.sync import Client
    except ImportError as exc:  # pragma: no cover — exercised only without asyncua
        raise OTConnectionError(
            "The 'asyncua' package is not installed. Install the OPC-UA "
            "connector: 'pip install iaiops[opcua]'."
        ) from exc

    if not target.endpoint_url:
        raise OTConnectionError(
            f"OPC-UA endpoint '{target.name}' has no endpoint_url. Add "
            f"'endpoint_url: opc.tcp://host:4840' to its config entry.",
            endpoint=target.name,
            protocol="opcua",
        )
    # asyncua's sync Client takes a per-request timeout in seconds; without it a
    # dead endpoint blocks on the OS TCP timeout (60-120s+) instead of failing fast.
    client = Client(target.endpoint_url, timeout=target.timeout_s)
    username = target.username
    password = target.password()
    if username:
        client.set_user(username)
    if password:
        client.set_password(password)
    # Mutual-TLS / application-certificate security. When a client cert + key are
    # configured, apply asyncua's security string
    # "Policy,Mode,cert,key[,server_cert]". No cert configured → anonymous /
    # username-password path is UNCHANGED (back-compat).
    if target.client_cert and target.client_key:
        policy = (
            target.security_policy
            if target.security_policy and target.security_policy != "None"
            else "Basic256Sha256"
        )
        mode = (
            target.security_mode
            if target.security_mode and target.security_mode != "None"
            else "SignAndEncrypt"
        )
        sec = f"{policy},{mode},{target.client_cert},{target.client_key}"
        if target.server_cert:
            sec += f",{target.server_cert}"
        client.set_security_string(sec)
    return client


def _translate_opcua(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map an asyncua exception to a teaching ``OTConnectionError``."""
    name = type(exc).__name__
    detail = str(exc).strip()[:200]
    endpoint = target.endpoint_url or target.name
    if "BadUserAccessDenied" in name or "BadIdentityToken" in detail:
        return OTConnectionError(
            f"OPC-UA authentication failed for '{target.name}' ({endpoint}). Check "
            f"the username and the stored password (see 'iaiops doctor'). {detail}",
            endpoint=endpoint,
            protocol="opcua",
        )
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)) or "Timeout" in name:
        return OTConnectionError(
            f"Could not reach OPC-UA endpoint '{target.name}' ({endpoint}). Check the "
            f"endpoint_url, that the server is running, and network/firewall. Point at "
            f"a local simulator to test. {detail}",
            endpoint=endpoint,
            protocol="opcua",
        )
    return OTConnectionError(
        f"OPC-UA operation on '{target.name}' ({endpoint}) failed: {detail}",
        endpoint=endpoint,
        protocol="opcua",
    )


__all__ = ["_build_opcua_client", "_translate_opcua"]
