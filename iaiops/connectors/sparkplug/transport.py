"""MQTT (Sparkplug B / UNS) transport: paho build + error translation (from connection.py).

The assembled ``mqtt_session`` lives in :mod:`iaiops.core.runtime.connection`
(via :func:`iaiops.core.runtime.session_factory.make_session`); tests keep
monkeypatching ``connection._build_mqtt_client``.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.session_factory import OTConnectionError


def _mqtt_port(target: TargetConfig) -> int:
    """Effective broker port: explicit, else 8883 with TLS / 1883 without."""
    return target.port or (8883 if target.use_tls else 1883)


def _build_mqtt_client(target: TargetConfig) -> Any:
    """Construct (but do not connect) a paho-mqtt Client for ``target``.

    Module-level so tests can monkeypatch it. paho-mqtt is pure Python. TLS and
    username/password (password from the encrypted store) are applied here.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:  # pragma: no cover — exercised only without paho
        raise OTConnectionError(
            "The 'paho-mqtt' package is not installed. Install the "
            "MQTT/Sparkplug connector: 'pip install iaiops[sparkplug]'."
        ) from exc

    if not target.host:
        raise OTConnectionError(
            f"MQTT endpoint '{target.name}' has no broker host. Add 'host: <broker>' "
            f"(or 'broker:') to its config entry.",
            endpoint=target.name,
            protocol="mqtt",
        )
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if target.username:
        client.username_pw_set(target.username, target.password() or None)
    # TLS: enabled by use_tls or by any cert path. A CA bundle verifies the broker;
    # a client cert+key give mutual auth. With none, tls_set() uses the system trust
    # store (server-auth only) — unchanged from before.
    if target.use_tls or target.ca_cert or target.client_cert:
        tls_kwargs: dict[str, str] = {}
        if target.ca_cert:
            tls_kwargs["ca_certs"] = target.ca_cert
        if target.client_cert and target.client_key:
            tls_kwargs["certfile"] = target.client_cert
            tls_kwargs["keyfile"] = target.client_key
        client.tls_set(**tls_kwargs)
    return client


def _connect_mqtt(client: Any, target: TargetConfig) -> None:
    """Connect to the broker and start the network loop."""
    client.connect(target.host, _mqtt_port(target))
    client.loop_start()


def _close_mqtt(client: Any) -> None:
    """Stop the network loop and disconnect (best-effort teardown)."""
    client.loop_stop()
    client.disconnect()


def _translate_mqtt(exc: Exception, target: TargetConfig) -> OTConnectionError:
    """Map a paho-mqtt exception to a teaching ``OTConnectionError``."""
    detail = str(exc).strip()[:200]
    endpoint = f"{target.host}:{_mqtt_port(target)}"
    return OTConnectionError(
        f"MQTT operation on '{target.name}' ({endpoint}) failed: {detail}. Check the "
        f"broker host/port, TLS/credentials, and that the broker is reachable. Point "
        f"at a local mosquitto broker to test.",
        endpoint=endpoint,
        protocol="mqtt",
    )


__all__ = ["_build_mqtt_client", "_close_mqtt", "_connect_mqtt", "_translate_mqtt"]
