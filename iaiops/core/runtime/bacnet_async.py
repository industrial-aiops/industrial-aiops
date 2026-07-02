"""Async→sync bridge for BAC0 (bacpypes3) — keeps the sync connector working.

Modern ``BAC0`` (2024+, the async-first rewrite over bacpypes3) is a coroutine
API: ``BAC0.lite(ip=...)`` must be constructed while an event loop is running, and
``who_is`` / ``read`` / ``readRange`` (and, depending on the build, ``write`` /
``cov`` / ``cancel_cov`` / ``disconnect``) are coroutines. The BACnet connector ops
are written synchronously (and stay that way — their public signatures never
change), so we bridge them onto a dedicated background event loop, exactly the
way :mod:`asyncua.sync` bridges asyncua: one long-lived loop thread per session,
every BAC0 call marshalled onto it with ``run_coroutine_threadsafe``.

The bridge is deliberately version-agnostic across the pinned range
(``BAC0>=2023.6,<2026``): each call is executed *inside* the loop thread and, if
the underlying method returns an awaitable, it is awaited there. So a sync-era
(2023.x) build and an async-first (2024+) build both work through the same facade.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any

# A construct/call must complete within these bounds or we surface a timeout
# rather than hang a tool forever. who_is waits for the segment to answer, so the
# call budget is generous; construction only brings the stack up.
CONSTRUCT_TIMEOUT_S = 30.0
CALL_TIMEOUT_S = 60.0
_LOOP_STOP_JOIN_S = 5.0


class BacnetLoopThread:
    """A background asyncio loop, running in its own daemon thread.

    BAC0's stack (and all its coroutines) live entirely on this one loop, so
    every BAC0 touch is thread-confined to it — the sync connector never runs
    BAC0 coroutines on the caller's thread.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="bacnet-loop", daemon=True
        )
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon_threadsafe(self._ready.set)
        self._loop.run_forever()

    def run_coro(self, coro: Any, timeout: float) -> Any:
        """Schedule ``coro`` on the loop thread and block for its result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def stop(self) -> None:
        """Stop the loop and join the thread (idempotent, never raises)."""
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except RuntimeError:  # pragma: no cover — loop already torn down
            pass
        self._thread.join(timeout=_LOOP_STOP_JOIN_S)
        try:
            self._loop.close()
        except Exception:  # noqa: BLE001 — close must not mask the real error
            pass


class BacnetSyncNetwork:
    """A synchronous facade over an async BAC0 network, on a dedicated loop.

    Exposes exactly the surface the BACnet ops call — ``who_is`` / ``read`` /
    ``readRange`` / ``write`` / ``cov`` / ``cancel_cov`` / ``cov_tasks`` /
    ``disconnect`` — each marshalled onto the owning loop thread. Awaitable
    results are awaited there; plain results pass straight through, so both the
    sync-era and async-first BAC0 builds work unchanged.
    """

    def __init__(
        self, net: Any, loop_thread: BacnetLoopThread, timeout: float = CALL_TIMEOUT_S
    ) -> None:
        self._net = net
        self._loop = loop_thread
        self._timeout = timeout

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Run ``self._net.<name>(*args, **kwargs)`` on the loop, await if needed."""

        async def _invoke() -> Any:
            result = getattr(self._net, name)(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

        return self._loop.run_coro(_invoke(), self._timeout)

    def who_is(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("who_is", *args, **kwargs)

    def read(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("read", *args, **kwargs)

    def readRange(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802 — BAC0 name
        return self._call("readRange", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("write", *args, **kwargs)

    def cov(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("cov", *args, **kwargs)

    def cancel_cov(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("cancel_cov", *args, **kwargs)

    @property
    def cov_tasks(self) -> Any:
        """Pass-through to BAC0's live COV task registry (read by the ops)."""
        return getattr(self._net, "cov_tasks", None)

    def disconnect(self) -> None:
        """Disconnect BAC0 on the loop thread, then always stop the loop."""
        try:
            self._call("disconnect")
        except Exception:  # noqa: BLE001 — teardown must still stop the loop
            pass
        finally:
            self._loop.stop()


def build_sync_network(lite: Any, ip: str) -> BacnetSyncNetwork:
    """Construct ``lite(ip=ip)`` on a fresh loop thread and wrap it as sync.

    ``lite`` is ``BAC0.lite`` (or ``BAC0.connect``). Modern BAC0's constructor
    schedules tasks on the running loop, so it MUST be built inside the loop
    thread. On any construction failure the loop thread is stopped before the
    error propagates, so no thread leaks.
    """
    loop_thread = BacnetLoopThread()

    async def _construct() -> Any:
        return lite(ip=ip)

    try:
        net = loop_thread.run_coro(_construct(), CONSTRUCT_TIMEOUT_S)
    except BaseException:
        loop_thread.stop()
        raise
    return BacnetSyncNetwork(net, loop_thread)


__all__ = ["BacnetLoopThread", "BacnetSyncNetwork", "build_sync_network"]
