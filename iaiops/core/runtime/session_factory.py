"""Generic per-call session factory for OT protocol connectors (B1 refactor).

Every protocol session in this codebase follows the same lifecycle: protocol
guard → build the client → connect (translating any failure into a teaching
:class:`OTConnectionError`) → yield the live client → translate any in-session
failure → always tear down, swallowing teardown errors so they never mask the
real one. :func:`make_session` captures that lifecycle ONCE; each connector
supplies only its protocol-specific pieces (build / connect / prepare / close /
translate) from its own ``transport`` module.

Downstream packages (e.g. ``iaiops-energy``) can register their own protocols by
calling :func:`make_session` with their own callables — nothing here needs to
change. The assembled sessions for the built-in protocols live in
:mod:`iaiops.core.runtime.connection`, which keeps the client *factories*
late-bound (module-level lambdas) so tests can monkeypatch
``connection._build_<proto>_client`` without a live device.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — import only for type annotations
    from iaiops.core.runtime.config import TargetConfig


class OTConnectionError(Exception):
    """An OT endpoint call failed; carries a teaching message + optional host."""

    def __init__(self, message: str, *, endpoint: str = "", protocol: str = "") -> None:
        self.endpoint = endpoint
        self.protocol = protocol
        super().__init__(message)


class OTProtocolError(OTConnectionError):
    """The device RESPONDED with a protocol-level exception (e.g. a Modbus
    exception response for an unmapped register).

    Subclasses :class:`OTConnectionError` so every existing ``except
    OTConnectionError`` keeps working, while diagnostics can distinguish
    "the device answered but rejected the request" (endpoint is alive) from
    a genuine transport/connect failure (endpoint unreachable).
    """


# Sentinel distinguishing "build never ran" from "build returned a falsy client":
# teardown must be skipped for the former but still attempted for the latter.
_UNBUILT: Any = object()

SessionFn = Callable[..., Any]


def make_session(
    *,
    protocol: str,
    build: Callable[[TargetConfig], Any],
    translate: Callable[[Exception, TargetConfig], OTConnectionError],
    connect: Callable[[Any, TargetConfig], None] | None = None,
    prepare: Callable[..., None] | None = None,
    close: Callable[[Any], None] | None = None,
    validate: Callable[[TargetConfig], None] | None = None,
    accept: tuple[str, ...] | None = None,
    build_in_session: bool = False,
    name: str | None = None,
) -> SessionFn:
    """Return a context-manager session function with the standard OT lifecycle.

    Args:
        protocol: Display name used in the protocol-guard teaching message.
        build: Constructs the (not yet connected) client from the target. May
            itself raise :class:`OTConnectionError` (missing extra / bad config).
        translate: Maps a raw driver exception to a teaching
            :class:`OTConnectionError` (connect and in-session failures alike).
        connect: Opens the connection (e.g. ``client.connect()``). Failures are
            translated; an :class:`OTConnectionError` it raises itself (e.g.
            Modbus ``connect() is False``) passes through untranslated. On
            connect failure teardown is NOT run (the client never opened).
        prepare: Optional in-session setup run just before the yield (e.g.
            EtherCAT ``config_init``); receives extra keyword arguments passed
            to the session call (e.g. ``map_pdo=True``, ``timeout_s=5``).
            Failures are translated like any in-session failure.
        close: Teardown; always attempted after the session body once the
            client was built, and any error is swallowed so it never masks the
            real one.
        validate: Optional pre-build target validation (after the guard),
            raising :class:`OTConnectionError` on bad config.
        accept: Protocol names the guard accepts (defaults to ``(protocol,)``,
            e.g. ``("ethernetip", "eip")``).
        build_in_session: Build INSIDE the translated block — for stacks whose
            constructor already performs I/O (PROFINET-DCP raw socket, BAC0
            UDP bind), so a build failure is translated, not raised raw.
        name: Optional ``__name__`` for the session function (debuggability).
    """
    allowed = accept or (protocol,)

    @contextmanager
    def session(target: TargetConfig, **kwargs: Any) -> Iterator[Any]:
        if target.protocol not in allowed:
            raise OTConnectionError(
                f"Endpoint '{target.name}' is protocol '{target.protocol}', "
                f"not {protocol}.",
                endpoint=target.name,
                protocol=target.protocol,
            )
        if validate is not None:
            validate(target)
        client: Any = _UNBUILT
        if not build_in_session:
            client = build(target)
            if connect is not None:
                try:
                    connect(client, target)
                except OTConnectionError:
                    raise
                except Exception as exc:  # noqa: BLE001 — translate any connect failure
                    raise translate(exc, target) from exc
        try:
            if build_in_session:
                client = build(target)
            if prepare is not None:
                prepare(client, target, **kwargs)
            yield client
        except OTConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 — translate any in-session failure
            raise translate(exc, target) from exc
        finally:
            if client is not _UNBUILT and close is not None:
                try:
                    close(client)
                except Exception:  # noqa: BLE001 — teardown must not mask the real error
                    pass

    session.__name__ = name or f"{protocol}_session"
    session.__qualname__ = session.__name__
    return session


__all__ = ["OTConnectionError", "OTProtocolError", "SessionFn", "make_session"]
