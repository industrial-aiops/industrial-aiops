"""No-egress registration gate: egress tools must not EXIST under IAIOPS_NO_EGRESS.

Sibling of ``tests/test_read_only_gate.py``, and deliberately ORTHOGONAL to it.
The read-only gate answers "can this server change the plant?"; this one answers
"can plant data leave this box?". A tool can be one, both, or neither:

* ``historian_push`` is ``risk_level="low"`` — the read-only gate keeps it, yet
  it ships telemetry to an external TSDB. Only this gate withholds it.
* ``mqtt_publish`` is BOTH (Sparkplug NCMD/DCMD is a real control path *and* a
  payload leaving the box) — either gate alone must withhold it.

Same enforcement philosophy: removal from the FastMCP registry, not a call-time
refusal. A tool a weak/local/prompt-injected model cannot SEE cannot be
hallucinated into a call, and an exfiltrated process value cannot be un-sent.

The registry is process-global, so every test here restores it.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.noegress import (
    NO_EGRESS_ENV,
    apply_no_egress,
    no_egress_enabled,
)
from mcp_server.readonly import READ_ONLY_ENV, WRITE_RISK_LEVELS, apply_read_only
from mcp_server.server import assert_all_tools_governed, mcp

#: Tools this repo classifies as egress today. This list is NOT what the gate
#: reads — the gate reads ``@governed_tool(egress=True)`` metadata. It exists so
#: a *silent* reclassification (someone dropping the flag) fails the suite, and
#: tests/test_egress_gate.py is what catches a NEW egress tool that never got
#: the flag in the first place.
_EXPECTED_EGRESS_TOOLS = frozenset(
    {
        "historian_push",
        "mqtt_publish",
        "rca_narrate",
        "stream_publish",
        "stream_publish_event",
    }
)


@pytest.fixture
def restorable_registry(full_tool_registry: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Full tool surface, with the process-global registry restored afterwards."""
    manager = mcp._tool_manager
    original = dict(manager._tools)
    try:
        yield original
    finally:
        manager._tools = original


def _egress_of(tool: Any) -> bool:
    return bool(getattr(getattr(tool, "fn", None), "_egress", False))


def _risk_of(tool: Any) -> str | None:
    return getattr(getattr(tool, "fn", None), "_risk_level", None)


def _egress_tool_names(registry: dict[str, Any]) -> set[str]:
    return {name for name, tool in registry.items() if _egress_of(tool)}


def _write_tool_names(registry: dict[str, Any]) -> set[str]:
    return {name for name, tool in registry.items() if _risk_of(tool) in WRITE_RISK_LEVELS}


# ── env parsing (same idiom as the read-only gate) ───────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " on "])
def test_no_egress_enabled_accepts_truthy_values(value: str):
    assert no_egress_enabled(value) is True


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "", "  ", "0", "false", "no", "off", "maybe"])
def test_no_egress_enabled_rejects_falsy_values(value: str | None):
    assert no_egress_enabled(value) is False


# ── the gate itself ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_gate_removes_every_egress_tool(restorable_registry):
    """After the gate no tool marked ``egress=True`` remains in the registry."""
    assert _egress_tool_names(restorable_registry), "expected egress tools before the gate"
    apply_no_egress(mcp)
    assert _egress_tool_names(mcp._tool_manager._tools) == set()


@pytest.mark.unit
def test_gate_returns_the_withheld_names(restorable_registry):
    """The return value is the exact, sorted set of names removed."""
    expected = sorted(_egress_tool_names(restorable_registry))
    withheld = apply_no_egress(mcp)
    assert list(withheld) == expected
    assert set(withheld).isdisjoint(mcp._tool_manager._tools)


@pytest.mark.unit
def test_gate_keeps_every_non_egress_tool(restorable_registry):
    """Nothing but egress tools is withheld — the rest of the surface is untouched."""
    expected_kept = {
        n for n in restorable_registry if n not in _egress_tool_names(restorable_registry)
    }
    apply_no_egress(mcp)
    assert set(mcp._tool_manager._tools) == expected_kept


@pytest.mark.unit
def test_gate_does_not_mutate_the_original_registry_dict(restorable_registry):
    """Immutability: the gate installs a NEW dict, leaving the old one intact."""
    before = dict(restorable_registry)
    apply_no_egress(mcp)
    assert restorable_registry == before
    assert mcp._tool_manager._tools is not restorable_registry


@pytest.mark.unit
def test_ungated_surface_is_unchanged(restorable_registry):
    """Falsy / unset env → nobody calls the gate → the egress tools stay."""
    assert no_egress_enabled(None) is False
    assert len(mcp._tool_manager._tools) == len(restorable_registry)
    assert _egress_tool_names(mcp._tool_manager._tools)


@pytest.mark.unit
def test_discovery_tool_survives_the_gate(restorable_registry):
    """``protocols_supported`` is how a model learns the posture — keep it."""
    apply_no_egress(mcp)
    assert "protocols_supported" in mcp._tool_manager._tools


@pytest.mark.unit
def test_uninspectable_registry_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mcp, "_tool_manager", object(), raising=False)
    with pytest.raises(RuntimeError, match="egress"):
        apply_no_egress(mcp)


@pytest.mark.unit
def test_gate_tolerates_a_tool_without_the_egress_flag(restorable_registry):
    """A tool decorated by an OLDER copy of ``@governed_tool`` has no ``_egress``.

    ``@governed_tool`` is shared with the iaiops-energy / iaiops-enterprise
    repos, so the gate must treat a missing flag as "not egress" rather than
    raising — the default has to preserve today's behaviour exactly.
    """
    manager = mcp._tool_manager
    manager._tools = {**restorable_registry, "flagless_tool": SimpleNamespace(fn=lambda: {})}
    withheld = apply_no_egress(mcp)
    assert "flagless_tool" not in withheld
    assert "flagless_tool" in manager._tools


# ── the classification ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_expected_tools_carry_the_egress_flag(restorable_registry):
    """The audited egress surface is exactly what is marked — no drift either way."""
    assert _egress_tool_names(restorable_registry) == set(_EXPECTED_EGRESS_TOOLS)


@pytest.mark.unit
def test_local_file_export_is_not_egress(restorable_registry):
    """``export_data`` writes a LOCAL file — it is not network egress.

    Pinned as a test because it is the classification a future reader is most
    likely to second-guess: "export" sounds like data leaving. It does not leave
    the box; withholding it would shrink the operator's own offline workflow for
    no security gain.
    """
    assert _egress_of(restorable_registry["export_data"]) is False
    apply_no_egress(mcp)
    assert "export_data" in mcp._tool_manager._tools


@pytest.mark.unit
def test_historian_push_escapes_the_read_only_gate(restorable_registry):
    """The reason this gate has to exist at all, pinned as an executable fact.

    ``historian_push`` is low-risk (it changes no plant state) so the read-only
    gate keeps it — yet it ships telemetry to an external TSDB. Without a second,
    orthogonal gate a "read-only" server would still exfiltrate.
    """
    assert _risk_of(restorable_registry["historian_push"]) not in WRITE_RISK_LEVELS
    apply_read_only(mcp)
    assert "historian_push" in mcp._tool_manager._tools


@pytest.mark.unit
def test_mqtt_publish_is_withheld_by_either_gate_alone(restorable_registry):
    """A tool that is both a control path and an egress path needs no coordination."""
    manager = mcp._tool_manager
    apply_read_only(mcp)
    assert "mqtt_publish" not in manager._tools

    manager._tools = dict(restorable_registry)
    apply_no_egress(mcp)
    assert "mqtt_publish" not in manager._tools


# ── composition ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_gates_compose_in_either_order(restorable_registry):
    """Both gates on → the surviving surface is identical whichever runs first.

    Each gate is a pure narrowing filter over an independent predicate, so the
    composition is order-insensitive. Pinned because the server applies them in
    one fixed order and a future reader should not have to re-derive that the
    order carries no meaning.
    """
    manager = mcp._tool_manager
    apply_read_only(mcp)
    apply_no_egress(mcp)
    read_only_first = set(manager._tools)

    manager._tools = dict(restorable_registry)
    apply_no_egress(mcp)
    apply_read_only(mcp)
    assert set(manager._tools) == read_only_first

    expected = set(restorable_registry) - _write_tool_names(restorable_registry)
    expected -= _egress_tool_names(restorable_registry)
    assert read_only_first == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("read_only", "no_egress"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_governance_assertion_holds_for_every_gate_combination(
    restorable_registry, read_only: bool, no_egress: bool
):
    """All four combinations still leave a fully governed registry.

    The gates run BEFORE ``assert_all_tools_governed`` in ``main()``; a gate that
    installed a malformed registry would turn a security switch into a startup
    crash (or worse, a silently ungoverned surface).
    """
    if read_only:
        apply_read_only(mcp)
    if no_egress:
        apply_no_egress(mcp)
    assert_all_tools_governed()
    assert mcp._tool_manager._tools, "a gate combination emptied the registry"


# ── the model must be TOLD, not left to infer ───────────────────────────────


@pytest.mark.unit
def test_protocols_supported_reports_no_egress_off(monkeypatch: pytest.MonkeyPatch):
    from mcp_server.tools.overview_tools import protocols_supported

    monkeypatch.delenv(NO_EGRESS_ENV, raising=False)
    assert protocols_supported()["no_egress_mode"] is False


@pytest.mark.unit
def test_protocols_supported_reports_no_egress_on(monkeypatch: pytest.MonkeyPatch):
    from mcp_server.tools.overview_tools import protocols_supported

    monkeypatch.setenv(NO_EGRESS_ENV, "1")
    result = protocols_supported()
    assert result["no_egress_mode"] is True
    assert NO_EGRESS_ENV in result["no_egress_note"]


@pytest.mark.unit
def test_protocols_supported_reports_both_postures_independently(
    monkeypatch: pytest.MonkeyPatch,
):
    """The two switches are reported separately — neither implies the other."""
    from mcp_server.tools.overview_tools import protocols_supported

    monkeypatch.setenv(READ_ONLY_ENV, "1")
    monkeypatch.delenv(NO_EGRESS_ENV, raising=False)
    result = protocols_supported()
    assert result["read_only_mode"] is True
    assert result["no_egress_mode"] is False

    monkeypatch.delenv(READ_ONLY_ENV, raising=False)
    monkeypatch.setenv(NO_EGRESS_ENV, "1")
    result = protocols_supported()
    assert result["read_only_mode"] is False
    assert result["no_egress_mode"] is True


# ── the decorator contract (shared with iaiops-energy / iaiops-enterprise) ───


@pytest.mark.unit
def test_governed_tool_defaults_to_not_egress():
    from iaiops.core.governance import governed_tool

    @governed_tool(risk_level="low")
    def plain() -> dict:
        return {}

    @governed_tool
    def bare() -> dict:
        return {}

    assert plain._egress is False
    assert bare._egress is False


@pytest.mark.unit
def test_governed_tool_records_the_egress_flag():
    from iaiops.core.governance import governed_tool

    @governed_tool(risk_level="low", egress=True)
    def ships_data() -> dict:
        return {}

    assert ships_data._egress is True
    # Orthogonality: the new kwarg must not disturb the existing metadata.
    assert ships_data._risk_level == "low"
    assert ships_data._is_governed_tool is True
