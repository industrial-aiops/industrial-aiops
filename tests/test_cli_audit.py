"""The CLI is audited on the same footing as the MCP server (see docs/HLD.md §3.1).

Read/write authorisation is NOT the tap's job — it is the caller's. The tap's
guarantee is that every call, on EITHER front-end, leaves an audit row. The MCP
wrappers carry ``@governed_tool`` directly; the CLI is governed centrally by
``iaiops.cli._govern.govern_app``. These tests pin that guarantee:

* every registered command is governed (a new command cannot ship ungoverned),
* Typer still builds each command's options (governance is signature-transparent),
* a CLI read leaves an audit row,
* a CLI **write** uses effect-based risk — the dry-run preview audits at ``low``
  (no approver), the real ``--apply`` write is ``high`` and approver-gated, so the
  CLI is not a governance backdoor around MOC yet previews stay friction-free,
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


def test_real_cli_write_is_denied_without_an_approver():
    """The real ``--apply`` write is approver-gated (parity with the MCP write
    tool): denied with a clean one-line error, and the denial is audited."""
    result = CliRunner().invoke(app, ["ethercat", "write-sdo", "0", "24698", "e803", "--apply"])
    assert result.exit_code == 1
    assert "Denied" in result.output
    rows = get_engine().query(tool="write_sdo_cmd")
    assert any(r["status"] == "denied" for r in rows)


def _effect_based_probe_app():
    """A synthetic write command marked like the real ones — no network needed."""
    from iaiops.cli._common import write_command
    from iaiops.cli._govern import govern_app

    calls: list[tuple[str, str]] = []
    sub = typer.Typer()

    @sub.command("w")
    @write_command
    def w(value: str, apply: bool = typer.Option(False, "--apply")) -> None:
        calls.append(("apply" if apply else "dry", value))

    root = typer.Typer()
    root.add_typer(sub, name="probe")
    govern_app(root)
    return root, calls


def test_write_dry_run_audits_low_and_is_not_approver_gated():
    """Effect-based risk: a dry-run preview changes nothing, so it audits at ``low``
    and runs WITHOUT an approver — previewing a write must stay friction-free."""
    root, calls = _effect_based_probe_app()
    result = CliRunner().invoke(root, ["probe", "w", "e803"])
    assert result.exit_code == 0, result.output
    assert calls == [("dry", "e803")]  # the body ran
    assert "Denied" not in result.output
    row = get_engine().query(tool="w")[-1]
    assert row["risk_level"] == "low" and row["status"] == "ok"


def test_real_write_is_high_and_approver_gated_and_body_does_not_run():
    """The ``--apply`` write is ``high``: denied without an approver, and the body
    never executes (no plant change on a denied call)."""
    root, calls = _effect_based_probe_app()
    result = CliRunner().invoke(root, ["probe", "w", "e803", "--apply"])
    assert result.exit_code == 1
    assert "Denied" in result.output
    assert calls == []  # the body did NOT run
    assert any(
        r["status"] == "denied" and r["risk_level"] == "high" for r in get_engine().query(tool="w")
    )


def test_write_commands_are_classified_as_writes():
    """The seven CLI write commands (six unique function names) carry the effect-
    based write marker, so their real ``--apply`` path is approver-gated."""
    writes = {
        cmd.callback.__name__
        for cmd in _all_commands(app)
        if cmd.callback is not None and getattr(cmd.callback, "_cli_apply_param", None) == "apply"
    }
    assert writes == {
        "write_sdo_cmd",
        "set_state_cmd",
        "write_db_cmd",
        "write_tag_cmd",
        "write_words_cmd",  # mc + fins share the name
        "publish_cmd",
    }


def test_delegating_cli_command_audits_exactly_once():
    """``iaiops historian query`` shares core read logic with the MCP tool; it must
    NOT reach through the governed MCP wrapper (that would double-audit and
    double-count the budget). Exactly one row, under the CLI command's name."""
    CliRunner().invoke(app, ["historian", "query", "--tag", "nope", "--endpoint", "plant1"])
    rows = get_engine().query()
    historian_rows = [r for r in rows if r["tool"] in {"query_cmd", "historian_query"}]
    assert len(historian_rows) == 1
    assert historian_rows[0]["tool"] == "query_cmd"


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
