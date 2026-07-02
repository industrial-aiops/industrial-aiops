"""Unit tests for the generic session factory (B1 refactor).

Exercises every branch of the lifecycle captured by ``make_session``: protocol
guard, pre-build validation, connect-failure translation (and pass-through of
teaching errors), in-session translation vs re-raise, kwargs plumbing to
``prepare``, build-inside-session mode, and the teardown-swallow discipline
(close always runs after connect, never masks the real error, and never runs
when the client was never built/connected).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from iaiops.core.runtime.session_factory import OTConnectionError, make_session

pytestmark = pytest.mark.unit


def _target(protocol: str = "fake", name: str = "line1") -> SimpleNamespace:
    return SimpleNamespace(protocol=protocol, name=name)


class _Client:
    def __init__(self, connect_exc: Exception | None = None) -> None:
        self.connect_exc = connect_exc
        self.connected = False
        self.closed = 0
        self.close_exc: Exception | None = None

    def connect(self) -> None:
        if self.connect_exc is not None:
            raise self.connect_exc
        self.connected = True

    def close(self) -> None:
        self.closed += 1
        if self.close_exc is not None:
            raise self.close_exc


def _translate(exc: Exception, target: Any) -> OTConnectionError:
    return OTConnectionError(
        f"fake operation on '{target.name}' failed: {exc}",
        endpoint=target.name,
        protocol="fake",
    )


def _make(client: _Client, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "protocol": "fake",
        "build": lambda target: client,
        "connect": lambda c, target: c.connect(),
        "close": lambda c: c.close(),
        "translate": _translate,
    }
    kwargs.update(overrides)
    return make_session(**kwargs)


# ── guard / validate ─────────────────────────────────────────────────────────


def test_protocol_guard_teaches_and_never_builds() -> None:
    built = []
    session = _make(_Client(), build=lambda t: built.append(t))
    with pytest.raises(OTConnectionError) as ei:
        with session(_target(protocol="other")):
            pass
    assert "is protocol 'other', not fake." in str(ei.value)
    assert ei.value.protocol == "other"
    assert not built


def test_accept_tuple_allows_protocol_aliases() -> None:
    client = _Client()
    session = _make(client, protocol="ethernetip", accept=("ethernetip", "eip"))
    with session(_target(protocol="eip")) as c:
        assert c is client


def test_validate_runs_after_guard_and_before_build() -> None:
    order: list[str] = []

    def validate(target: Any) -> None:
        order.append("validate")
        raise OTConnectionError("no host", endpoint=target.name, protocol="fake")

    client = _Client()
    session = _make(client, validate=validate, build=lambda t: order.append("build"))
    with pytest.raises(OTConnectionError, match="no host"):
        with session(_target()):
            pass
    assert order == ["validate"]
    assert client.closed == 0


# ── build / connect phase ────────────────────────────────────────────────────


def test_build_teaching_error_propagates_and_skips_close() -> None:
    client = _Client()

    def build(target: Any) -> Any:
        raise OTConnectionError("extra not installed", protocol="fake")

    session = _make(client, build=build)
    with pytest.raises(OTConnectionError, match="extra not installed"):
        with session(_target()):
            pass
    assert client.closed == 0


def test_connect_failure_is_translated_and_close_not_called() -> None:
    client = _Client(connect_exc=TimeoutError("timed out"))
    session = _make(client)
    with pytest.raises(OTConnectionError) as ei:
        with session(_target()):
            pass
    assert "fake operation on 'line1' failed: timed out" in str(ei.value)
    assert isinstance(ei.value.__cause__, TimeoutError)
    assert client.closed == 0  # never connected → teardown must not run


def test_connect_raising_teaching_error_passes_through_untranslated() -> None:
    teaching = OTConnectionError("could not connect (connect() is False)", protocol="fake")
    client = _Client(connect_exc=teaching)
    session = _make(client)
    with pytest.raises(OTConnectionError) as ei:
        with session(_target()):
            pass
    assert ei.value is teaching


# ── yield / in-session phase ─────────────────────────────────────────────────


def test_success_yields_client_and_closes_once() -> None:
    client = _Client()
    session = _make(client)
    with session(_target()) as c:
        assert c is client
        assert client.connected
        assert client.closed == 0  # not torn down while in use
    assert client.closed == 1


def test_in_session_failure_is_translated_and_still_closes() -> None:
    client = _Client()
    session = _make(client)
    with pytest.raises(OTConnectionError) as ei:
        with session(_target()):
            raise ValueError("bad response")
    assert "failed: bad response" in str(ei.value)
    assert isinstance(ei.value.__cause__, ValueError)
    assert client.closed == 1


def test_in_session_teaching_error_reraised_untranslated() -> None:
    client = _Client()
    session = _make(client)
    teaching = OTConnectionError("already taught", protocol="fake")
    with pytest.raises(OTConnectionError) as ei:
        with session(_target()):
            raise teaching
    assert ei.value is teaching
    assert client.closed == 1


def test_prepare_receives_session_kwargs_and_failures_translate() -> None:
    seen: dict[str, Any] = {}
    client = _Client()

    def prepare(c: Any, target: Any, *, map_pdo: bool = False) -> None:
        seen["map_pdo"] = map_pdo
        if map_pdo:
            raise RuntimeError("config_map failed")

    session = _make(client, prepare=prepare)
    with session(_target()):
        pass
    assert seen["map_pdo"] is False
    with pytest.raises(OTConnectionError, match="config_map failed"):
        with session(_target(), map_pdo=True):
            pass
    assert client.closed == 2  # teardown ran on both paths


# ── teardown-swallow discipline ──────────────────────────────────────────────


def test_close_error_is_swallowed_on_success() -> None:
    client = _Client()
    client.close_exc = RuntimeError("close blew up")
    session = _make(client)
    with session(_target()) as c:
        assert c is client
    assert client.closed == 1  # no exception escaped


def test_close_error_never_masks_the_real_error() -> None:
    client = _Client()
    client.close_exc = RuntimeError("close blew up")
    session = _make(client)
    with pytest.raises(OTConnectionError, match="the real failure"):
        with session(_target()):
            raise ValueError("the real failure")
    assert client.closed == 1


# ── build_in_session mode (PROFINET / BACnet shape) ──────────────────────────


def test_build_in_session_translates_constructor_failure_and_skips_close() -> None:
    closed: list[Any] = []

    def build(target: Any) -> Any:
        raise PermissionError("raw socket not permitted")

    session = make_session(
        protocol="fake",
        build=build,
        build_in_session=True,
        close=lambda c: closed.append(c),
        translate=_translate,
    )
    with pytest.raises(OTConnectionError) as ei:
        with session(_target()):
            pass
    assert isinstance(ei.value.__cause__, PermissionError)
    assert closed == []  # nothing was built → nothing to close


def test_build_in_session_success_yields_and_closes() -> None:
    client = _Client()
    session = make_session(
        protocol="fake",
        build=lambda target: client,
        build_in_session=True,
        close=lambda c: c.close(),
        translate=_translate,
    )
    with session(_target()) as c:
        assert c is client
    assert client.closed == 1


def test_session_function_name_defaults_and_overrides() -> None:
    assert _make(_Client()).__name__ == "fake_session"
    assert _make(_Client(), name="fake_master").__name__ == "fake_master"
