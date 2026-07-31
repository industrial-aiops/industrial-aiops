"""No plant write reaches the wire without a named approver — on every write tool.

The approval gate is well covered against *synthetic* ``@governed_tool`` functions
(``test_policy_hardening.py``, ``test_effect_based_risk.py``, ``test_approval_tokens.py``)
and against a *synthetic* CLI command (``test_cli_audit.py``). What none of them
covered is the surface a client actually calls: the ten registered high-risk MCP
write tools. A tool that lost its ``risk_level="high"`` in a refactor would have
kept every one of those tests green.

Each tool is driven end to end here, three ways:

* **no approver → denied, and the body never runs.** The assertion that matters is
  the second one. "It raised" only proves an exception; what the product promises is
  that nothing reached the device.
* **approver recorded → the body runs.** Without this the suite could pass by denying
  everything, which is not a gate but a brick.
* **dry-run preview → runs with no approver.** Effect-based risk: previewing a write
  changes nothing, so it must stay friction-free. A gate that also blocked previews
  would push operators toward skipping the preview.

Args are per tool because the signatures differ; values are inert placeholders that
never travel (in the denied case the gate fires first, in the others the connector
call is replaced by a spy).
"""

from __future__ import annotations

from typing import Any

import pytest

from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.decorators import PolicyDenied
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine

# tool name → (module holding the connector call, ops attribute, kwargs)
WRITE_TOOLS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "s7_write_db": (
        "mcp_server.tools.s7_tools",
        "s7_write_db",
        {"db": 1, "dtype": "INT", "start": 0, "value": 5},
    ),
    "mc_write_words": (
        "mcp_server.tools.mc_tools",
        "mc_write_words",
        {"headdevice": "D100", "values": [1]},
    ),
    "fins_write_words": (
        "mcp_server.tools.fins_tools",
        "fins_write_words",
        {"area": "DM", "address": 100, "values": [1]},
    ),
    "eip_write_tag": (
        "mcp_server.tools.eip_tools",
        "eip_write_tag",
        {"tag": "Setpoint", "value": 1},
    ),
    "ethercat_write_sdo": (
        "mcp_server.tools.ethercat_tools",
        "ethercat_write_sdo",
        {"slave": 0, "index": 24698, "value": "e803"},
    ),
    "ethercat_set_state": (
        "mcp_server.tools.ethercat_tools",
        "ethercat_set_state",
        {"state": "PREOP"},
    ),
    "profinet_dcp_set": (
        "mcp_server.tools.profinet_tools",
        "profinet_dcp_set",
        {"mac": "00:11:22:33:44:55", "set_name": "plc1"},
    ),
    "bacnet_write_property": (
        "mcp_server.tools.bacnet_tools",
        "bacnet_write_property",
        {"address": "10.0.0.5", "object_type": "analogValue", "instance": 1, "value": 21.5},
    ),
    # The BAS tool delegates to ``ops.command`` — the ops name need not match the
    # tool name, which is why this table names both.
    "bas_command": (
        "mcp_server.tools.bas_tools",
        "command",
        {
            "base_url": "https://bas.example",
            "vendor": "niagara",
            "point_id": "p1",
            "value": 21.5,
        },
    ),
    "mqtt_publish": (
        "mcp_server.tools.sparkplug_tools",
        "mqtt_publish",
        {"topic": "factory/line1/cmd", "payload": "{}"},
    ),
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OPCUA_AUDIT_APPROVED_BY", raising=False)
    monkeypatch.delenv("OPCUA_AUDIT_RATIONALE", raising=False)
    reset_engine()
    reset_policy_engine()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")
    yield
    reset_engine()
    reset_policy_engine()


@pytest.fixture
def registry(full_tool_registry) -> dict[str, Any]:
    return full_tool_registry


def _spy_on_connector(monkeypatch: pytest.MonkeyPatch, module_path: str, attr: str) -> list:
    """Replace the connector call the tool delegates to; return the call log.

    Also neutralises endpoint resolution where the tool uses it: ``_target`` runs
    inside the tool body and would raise "no endpoints configured" before the spy
    is reached, which would look like a denial without being one. The BAS tool
    addresses its controller by URL and imports no ``_target``, hence the guard.
    """
    import importlib

    module = importlib.import_module(module_path)
    calls: list = []

    def _spy(*args: Any, **kwargs: Any) -> dict:
        calls.append((args, kwargs))
        return {"applied": True, "dry_run": False}

    monkeypatch.setattr(module.ops, attr, _spy)
    if hasattr(module, "_target"):
        monkeypatch.setattr(module, "_target", lambda name=None: object())
    return calls


@pytest.mark.unit
def test_the_table_covers_every_high_risk_write(registry) -> None:
    """A new write tool must be added here, not silently skipped."""
    declared = {
        name
        for name, tool in registry.items()
        if getattr(tool.fn, "_risk_level", "low") in ("high", "critical")
    }
    assert declared == set(WRITE_TOOLS), (
        f"write tools missing from this contract: {sorted(declared - set(WRITE_TOOLS))}; "
        f"stale entries: {sorted(set(WRITE_TOOLS) - declared)}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_without_an_approver_is_denied_and_never_reaches_the_device(
    name: str, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path, attr, kwargs = WRITE_TOOLS[name]
    calls = _spy_on_connector(monkeypatch, module_path, attr)

    with pytest.raises(PolicyDenied):
        registry[name].fn(dry_run=False, **kwargs)

    assert calls == [], f"{name} reached the connector on a denied call"


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_with_a_recorded_approver_runs(
    name: str, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this the suite could pass by denying everything."""
    module_path, attr, kwargs = WRITE_TOOLS[name]
    calls = _spy_on_connector(monkeypatch, module_path, attr)
    monkeypatch.setenv("OPCUA_AUDIT_APPROVED_BY", "alice")

    registry[name].fn(dry_run=False, **kwargs)

    assert len(calls) == 1, f"{name} did not reach the connector with an approver recorded"
    row = get_engine().query(tool=name)[-1]
    assert row["approved_by"] == "alice"
    assert row["risk_level"] == "high", "an applied write must audit at its declared risk"


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_dry_run_preview_needs_no_approver(
    name: str, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Effect-based risk: a preview changes nothing, so it audits at ``low`` and
    runs without an approver. A gate that blocked previews too would teach
    operators to skip the preview and go straight to the write."""
    module_path, attr, kwargs = WRITE_TOOLS[name]
    calls = _spy_on_connector(monkeypatch, module_path, attr)

    registry[name].fn(dry_run=True, **kwargs)

    assert len(calls) == 1, f"{name} preview was blocked without an approver"
    assert get_engine().query(tool=name)[-1]["risk_level"] == "low"
