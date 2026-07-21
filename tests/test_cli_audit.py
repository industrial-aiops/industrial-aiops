"""The CLI is audited on the same footing as the MCP server (see docs/HLD.md §3.1).

Read/write authorisation is NOT the tap's job — it is the caller's. The tap's
guarantee is that every call, on EITHER front-end, leaves an audit row. The MCP
wrappers carry ``@governed_tool`` directly; the CLI is governed centrally by
``iaiops.cli._govern.govern_app``. These tests pin that guarantee:

* every registered command is governed (a new command cannot ship ungoverned),
* Typer still builds each command's options (governance is signature-transparent),
* a CLI read leaves an audit row,
* a CLI **write** is approver-gated (denied without an approver), matching the
  MCP write tool — the CLI is not a governance backdoor around MOC,
* a credential-bearing command (``secret set``) does not log the secret value.
"""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from iaiops.cli._root import app
from iaiops.core.governance.audit import get_engine


def _all_commands(a: typer.Typer):
    yield from getattr(a, "registered_commands", [])
    for grp in getattr(a, "registered_groups", []):
        yield from _all_commands(grp.typer_instance)


# ── coverage: no command ships ungoverned ────────────────────────────────────


def test_every_registered_command_is_governed():
    """The only exception is the ``iaiops mcp`` launcher (``no_audit``); its
    spawned tools are each governed on their own."""
    ungoverned = [
        cmd.callback.__name__
        for cmd in _all_commands(app)
        if cmd.callback is not None
        and not getattr(cmd.callback, "_is_governed_tool", False)
        and not getattr(cmd.callback, "_cli_skip_govern", False)
    ]
    assert ungoverned == [], f"ungoverned CLI commands: {ungoverned}"


def test_mcp_launcher_is_deliberately_excluded():
    launchers = [
        cmd.callback.__name__
        for cmd in _all_commands(app)
        if cmd.callback is not None and getattr(cmd.callback, "_cli_skip_govern", False)
    ]
    assert launchers == ["mcp_cmd"]


def test_governance_is_signature_transparent():
    """A governed write command still exposes its options/args through Typer."""
    result = CliRunner().invoke(app, ["ethercat", "write-sdo", "--help"])
    assert result.exit_code == 0
    assert "--apply" in result.output
    assert "SLAVE" in result.output.upper()


# ── behaviour: reads audit, writes are approver-gated ────────────────────────


def test_cli_read_leaves_an_audit_row():
    """``iaiops protocols`` is an offline read; invoking it must audit."""
    result = CliRunner().invoke(app, ["protocols"])
    assert result.exit_code == 0
    rows = get_engine().query(tool="protocols_cmd")
    assert len(rows) >= 1
    assert rows[0]["status"] == "ok"


def test_cli_write_is_denied_without_an_approver():
    """A high-risk CLI write is approver-gated (parity with the MCP write tool):
    denied with a clean one-line error, and the denial is audited."""
    result = CliRunner().invoke(app, ["ethercat", "write-sdo", "0", "24698", "e803", "--apply"])
    assert result.exit_code == 1
    assert "Denied" in result.output
    rows = get_engine().query(tool="write_sdo_cmd")
    assert any(r["status"] == "denied" for r in rows)


def test_write_commands_are_high_risk():
    """The eight CLI write commands carry HIGH risk, so they are approver-gated."""
    high = {
        cmd.callback.__name__
        for cmd in _all_commands(app)
        if cmd.callback is not None and getattr(cmd.callback, "_risk_level", "low") == "high"
    }
    assert high == {
        "write_sdo_cmd",
        "set_state_cmd",
        "write_db_cmd",
        "write_tag_cmd",
        "write_words_cmd",  # mc + fins share the name
        "publish_cmd",
    }


# ── credentials never reach the audit row ────────────────────────────────────


def test_secret_set_does_not_log_the_secret_value(monkeypatch):
    """``iaiops secret set`` audits that a secret was stored, never its value."""
    monkeypatch.setenv("IAIOPS_MASTER_PASSWORD", "test-master-pw")
    result = CliRunner().invoke(app, ["secret", "set", "plant1", "--value", "SUPERSECRET"])
    assert result.exit_code == 0
    rows = get_engine().query(tool="secret_set")
    assert rows, "secret set was not audited"
    blob = str(rows[-1])
    assert "SUPERSECRET" not in blob
    assert "***" in str(rows[-1]["params"])
