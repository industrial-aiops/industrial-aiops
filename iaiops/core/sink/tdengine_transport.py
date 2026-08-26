"""How a TDengine connection is opened — native, REST or WebSocket.

TDengine ships three client transports, and until now this package could only
use the first:

* ``native`` — ``taos``, the C client. Fast, and the reason CI fetches a
  **vendor tarball pinned by sha256**: ``libtaos`` is not on PyPI, so the
  binding is unusable on any machine that has not installed it out of band
  (every macOS dev box here, among others).
* ``rest`` — ``taosrest``, plain HTTP on port 6041. Ships *inside* taospy, needs
  no native library at all, and is the transport a sealed site is most likely to
  be allowed through a firewall.
* ``websocket`` — ``taos-ws-py``, a self-contained wheel on the same port.

All three expose the same DB-API surface (``connect() → cursor() →
execute()/fetchall()``), which is what makes this a transport choice rather than
three sinks: the SQL, the DDL and the row handling above are identical, and the
live tests run the same assertions over each.

Chosen with ``transport=`` on the sink/reader (config: ``transport: rest``).
Default stays ``native`` — an existing deployment must not change behaviour
because this module appeared.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.sink.base import SinkError

#: Canonical names + the aliases a config file is likely to carry.
_ALIASES = {
    "native": "native",
    "taos": "native",
    "c": "native",
    "rest": "rest",
    "http": "rest",
    "taosrest": "rest",
    "websocket": "websocket",
    "ws": "websocket",
    "taosws": "websocket",
}

TRANSPORTS = ("native", "rest", "websocket")

#: taosAdapter serves both REST and WebSocket here; the native client uses 6030.
DEFAULT_NATIVE_PORT = 6030
DEFAULT_ADAPTER_PORT = 6041


def resolve_transport(value: str | None) -> str:
    """Canonical transport name; raises with the supported list on a typo."""
    raw = (value or "native").strip().lower()
    if raw not in _ALIASES:
        raise SinkError(
            f"Unknown TDengine transport '{value}'. Supported: {', '.join(TRANSPORTS)} "
            f"(aliases: http→rest, ws→websocket, taos→native)."
        )
    return _ALIASES[raw]


def default_port(transport: str) -> int:
    """The port a transport uses when the config does not say."""
    return DEFAULT_NATIVE_PORT if transport == "native" else DEFAULT_ADAPTER_PORT


def open_connection(
    transport: str, host: str, port: int, user: str, password: str, database: str = ""
) -> Any:
    """Open a TDengine connection over ``transport``.

    Every branch raises a teaching :class:`SinkError` naming the extra to install,
    because the three clients fail differently: the native one raises at IMPORT
    time when libtaos is missing (not at connect), which is why its except clause
    is broader than an ImportError.
    """
    if transport == "rest":
        try:
            import taosrest
        except ImportError as exc:  # pragma: no cover — only without taospy
            raise SinkError(
                "The 'taospy' package is not installed (it provides taosrest). "
                "Install the TDengine sink: 'pip install iaiops[tdengine-rest]'."
            ) from exc
        return taosrest.connect(
            url=f"http://{host}:{port}",
            user=user,
            password=password,
            **({"database": database} if database else {}),
        )

    if transport == "websocket":
        try:
            import taosws
        except ImportError as exc:  # pragma: no cover — only without taos-ws-py
            raise SinkError(
                "The 'taos-ws-py' package is not installed. Install the TDengine "
                "WebSocket transport: 'pip install iaiops[tdengine-ws]'."
            ) from exc
        dsn = f"taosws://{user}:{password}@{host}:{port}"
        return taosws.connect(f"{dsn}/{database}" if database else dsn)

    try:
        import taos
    except ImportError as exc:  # pragma: no cover — only without taospy
        raise SinkError(
            "The 'taospy' package is not installed. Install the TDengine sink: "
            "'pip install iaiops[tdengine]'."
        ) from exc
    except Exception as exc:  # noqa: BLE001 — taospy dlopens libtaos AT IMPORT
        raise SinkError(
            f"The native TDengine client (libtaos) could not be loaded: {exc}. It is "
            f"a vendor download, not a PyPI wheel — or use a transport that needs no "
            f"native library: '--transport rest' (HTTP :{DEFAULT_ADAPTER_PORT}) or "
            f"'--transport websocket' on the CLI; transport='rest' via the MCP tool "
            f"or the config's 'historian:' block."
        ) from exc
    return taos.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        **({"database": database} if database else {}),
    )


__all__ = ["TRANSPORTS", "default_port", "open_connection", "resolve_transport"]
