"""NATS stream publisher — publish normalized points + events to a NATS subject tree.

``nats-py`` is an OPTIONAL extra (``pip install iaiops[nats]``) imported LAZILY. nats-py is asyncio;
we bridge it with a short-lived event loop per batch (connect → publish all → flush → drain), so the
caller stays synchronous like the rest of iaiops. The network delivery is isolated behind
``_deliver(messages)`` so the shaping/routing is fully mock-testable without a broker
(待核实 against a live NATS server).
"""

from __future__ import annotations

from iaiops.core.egress.base import EgressError, encode, points_to_messages


class NATSPublisher:
    """Uniform publisher over NATS core (待核实)."""

    def __init__(self, servers: str = "nats://localhost:4222", subject_prefix: str = "iaiops",
                 token: str = "", tls: bool = False, timeout_s: float = 10.0) -> None:
        self._servers = servers or "nats://localhost:4222"
        self._subject_prefix = subject_prefix or "iaiops"
        self._token = token or ""
        self._tls = bool(tls)
        self._timeout = float(timeout_s or 10.0)

    def publish_points(self, points: list[dict]) -> int:
        """Publish numeric points to ``<prefix>.tag.<metric>``; returns the count published."""
        messages = points_to_messages(points, self._subject_prefix)
        wire = [(subject, encode(payload)) for subject, payload in messages]
        self._deliver(wire)
        return len(wire)

    def publish_event(self, subject: str, event: dict) -> int:
        """Publish one structured event (alarm / RCA verdict) to ``<prefix>.<subject>``."""
        subj = f"{self._subject_prefix}.{(subject or 'event').strip('.')}"
        self._deliver([(subj, encode(event or {}))])
        return 1

    def _deliver(self, messages: list[tuple[str, bytes]]) -> None:
        """Connect, publish every message, flush, and close — isolated for mock testing."""
        if not messages:
            return
        try:
            import asyncio

            import nats
        except ImportError as exc:  # pragma: no cover — only without nats-py
            raise EgressError(
                "The 'nats-py' package is not installed. Install the NATS publisher: "
                "'pip install iaiops[nats]'."
            ) from exc

        async def _run() -> None:
            servers = [srv.strip() for srv in self._servers.split(",") if srv.strip()]
            opts: dict = {"servers": servers, "connect_timeout": self._timeout}
            if self._token:
                opts["token"] = self._token
            if self._tls:
                opts["tls"] = True
            nc = await nats.connect(**opts)
            try:
                for subject, data in messages:
                    await nc.publish(subject, data)
                await nc.flush(timeout=self._timeout)
            finally:
                await nc.drain()

        try:
            asyncio.run(_run())
        except EgressError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any bus/loop failure as a teaching error
            raise EgressError(f"NATS publish to {self._servers} failed: {exc}") from exc

    def close(self) -> None:  # connection is per-batch; nothing persistent to close.
        return None


__all__ = ["NATSPublisher"]
