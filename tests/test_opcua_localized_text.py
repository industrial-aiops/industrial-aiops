"""An OPC UA LocalizedText value is its text, not a Python repr.

Seen live (2026-10-18, the OPC Foundation reference PackML server): collecting
``ExecuteState/CurrentState`` stored ``LocalizedText(Locale=None, Text='Idle')``.
``_coerce_value`` sanitised anything non-scalar with ``str()``, so the stored
value carried the class name and both fields. A text ``running_when`` could
never match it, and ``oee measure`` refused with ``no_running_state_matched`` —
safe, but only because nothing could ever be measured.

The locale is dropped on purpose: what a person declares is the word the device
sends, and a declaration in the wrong language still matches nothing — the
same refusal, now for the right reason. Companion-spec SUGGESTIONS stay on the
language-independent ``CurrentState/Number`` (companion_specs).
"""

from __future__ import annotations

import socket
import sqlite3

import pytest

from iaiops.connectors.opcua.ops import _coerce_value, opcua_session, read_node, read_observation
from iaiops.core.collect.plan import CollectionPlan
from iaiops.core.collect.reader import polls_are_fresh, session_builder_for, session_read_for
from iaiops.core.collect.runner import run_collection
from iaiops.core.runtime.config import MonitorTag, TargetConfig


@pytest.mark.unit
def test_a_localized_text_coerces_to_its_text():
    from asyncua import ua

    assert _coerce_value(ua.LocalizedText("Execute", "en")) == "Execute"
    assert _coerce_value(ua.LocalizedText("Ausführen", "de-DE")) == "Ausführen"


@pytest.mark.unit
def test_an_empty_localized_text_is_empty_not_a_repr():
    from asyncua import ua

    assert _coerce_value(ua.LocalizedText()) == ""


@pytest.mark.unit
def test_an_array_of_localized_texts_is_an_array_of_texts():
    from asyncua import ua

    assert _coerce_value([ua.LocalizedText("A"), ua.LocalizedText("B", "en")]) == ["A", "B"]


@pytest.mark.unit
def test_device_text_is_still_sanitised():
    from asyncua import ua

    out = _coerce_value(ua.LocalizedText("Idle\x00\x1b[31m" + "x" * 400))
    assert "\x00" not in out and "\x1b" not in out and len(out) <= 256


@pytest.mark.unit
def test_other_structured_values_are_unchanged():
    """Only LocalizedText is unwrapped; anything else keeps the old sanitised form."""
    from asyncua import ua

    assert _coerce_value(ua.QualifiedName("Name", 2)) == str(ua.QualifiedName("Name", 2))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server():
    from asyncua import ua
    from asyncua.sync import Server

    url = f"opc.tcp://127.0.0.1:{_free_port()}/text"
    srv = Server()
    srv.set_endpoint(url)
    idx = srv.register_namespace("http://vendor.example/line")
    state = srv.nodes.objects.add_variable(idx, "CurrentState", ua.LocalizedText("Execute", "en"))
    srv.start()
    try:
        yield {"url": url, "ref": state.nodeid.to_string()}
    finally:
        srv.stop()


def _target(url: str) -> TargetConfig:
    return TargetConfig(name="line1", protocol="opcua", endpoint_url=url)


@pytest.mark.integration
def test_every_read_path_returns_the_text(server):
    target = _target(server["url"])
    assert read_node(target, server["ref"])["value"] == "Execute"
    with opcua_session(target) as client:
        assert read_observation(client, server["ref"])[0] == "Execute"


@pytest.mark.integration
def test_collected_text_matches_a_declared_text_running_state(server, tmp_path):
    db = tmp_path / "s.db"
    plan = CollectionPlan(endpoint="line1", tags=(server["ref"],), duration_s=60, interval_ms=100)
    result = run_collection(
        plan,
        _target(server["url"]),
        reader=session_read_for("opcua"),
        db_path=db,
        max_iterations=3,
        session_builder=session_builder_for("opcua"),
        fresh_each_read=polls_are_fresh("opcua"),
    )
    assert result.samples_written == 3
    with sqlite3.connect(db) as conn:
        values = [v for (v,) in conn.execute("SELECT value FROM samples")]
    assert values == ["Execute"] * 3
    tag = MonitorTag(ref=server["ref"], role="run_state", running_when=("execute",))
    assert all(tag.is_running(v) for v in values)
