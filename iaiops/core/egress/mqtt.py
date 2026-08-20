"""MQTT stream publisher — publish normalized points + events into a broker / UNS topic tree.

``paho-mqtt`` is an OPTIONAL extra (``pip install iaiops[mqtt]``) imported LAZILY. The connection is
per-batch (connect → publish all → wait for delivery → disconnect), so the caller stays synchronous
like the rest of iaiops. Network delivery is isolated behind ``_deliver(messages)`` so the
shaping/routing is fully mock-testable without a broker.

This is the *telemetry* direction and it is deliberately NOT the same tool as the connector's
``mqtt_publish``. That one takes an arbitrary topic and an arbitrary payload, which is
indistinguishable from a Sparkplug NCMD/DCMD command to a live controller — hence its
``risk_level="high"``. Here the topic is always derived from an operator-set prefix plus the metric
name, and the payload is always a telemetry record, so it carries the same risk class as the NATS
publisher (待核实 against a live production broker).
"""

from __future__ import annotations

from iaiops.core.egress.base import EgressError, encode, points_to_mqtt_messages


class MQTTPublisher:
    """Uniform publisher over MQTT (待核实)."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 0,
        topic_prefix: str = "iaiops",
        username: str = "",
        password: str = "",
        use_tls: bool = False,
        qos: int = 0,
        retain: bool = False,
        timeout_s: float = 10.0,
    ) -> None:
        self._host = host or "localhost"
        self._use_tls = bool(use_tls)
        self._port = int(port or 0) or (8883 if self._use_tls else 1883)
        self._topic_prefix = topic_prefix or "iaiops"
        self._username = username or ""
        self._password = password or ""
        # Clamped, not validated: MQTT defines exactly 0/1/2, and a caller that
        # passes 3 means "as reliable as possible", not "fail the batch".
        self._qos = max(0, min(int(qos or 0), 2))
        self._retain = bool(retain)
        self._timeout = float(timeout_s or 10.0)

    def publish_points(self, points: list[dict]) -> int:
        """Publish numeric points to ``<prefix>/<metric>`` levels; returns the count published."""
        messages = points_to_mqtt_messages(points, self._topic_prefix)
        wire = [(topic, encode(payload)) for topic, payload in messages]
        self._deliver(wire)
        return len(wire)

    def publish_event(self, subject: str, event: dict) -> int:
        """Publish one structured event (alarm / RCA verdict) to ``<prefix>/<subject>``."""
        topic = f"{self._topic_prefix}/{(subject or 'event').strip('/')}"
        self._deliver([(topic, encode(event or {}))])
        return 1

    def _deliver(self, messages: list[tuple[str, bytes]]) -> None:
        """Connect, publish every message, wait for delivery, disconnect — isolated for testing."""
        if not messages:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover — only without paho-mqtt
            raise EgressError(
                "The 'paho-mqtt' package is not installed. Install the MQTT publisher: "
                "'pip install iaiops[mqtt]'."
            ) from exc

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password or None)
        if self._use_tls:
            client.tls_set()

        try:
            # HARD outer bound, and it has to be ours. paho's ``connect`` blocks on the
            # socket connect with no timeout of its own beyond ``keepalive`` (which
            # governs the session, not the attempt), so an unreachable broker — a
            # typo'd address or a sealed site — hangs the caller. This tool is
            # reachable from an MCP client and ``@governed_tool``'s ``timeout_seconds``
            # is advisory (it warns; it does not cancel), so a bounded failure the
            # caller can act on beats an accurate one it never sees.
            client._connect_timeout = self._timeout  # noqa: SLF001 — paho exposes no setter
            client.connect(self._host, self._port, keepalive=max(int(self._timeout), 5))
            client.loop_start()
            try:
                for topic, data in messages:
                    info = client.publish(topic, payload=data, qos=self._qos, retain=self._retain)
                    # QoS 0 is fire-and-forget: the broker never acknowledges, so
                    # waiting would block for the full timeout on every message.
                    if self._qos > 0:
                        info.wait_for_publish(timeout=self._timeout)
            finally:
                client.loop_stop()
                client.disconnect()
        except EgressError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any broker/socket failure as teaching
            raise EgressError(
                f"MQTT publish to {self._host}:{self._port} failed: {exc}. "
                f"Check the broker address, that it is reachable from this host, and "
                f"the credentials if the broker requires them."
            ) from exc

    def close(self) -> None:  # connection is per-batch; nothing persistent to close.
        return None


__all__ = ["MQTTPublisher"]
