"""Credential-redaction contract: a secret passed as a parameter must never be
audited in the clear — on EITHER front-end.

``@governed_tool`` writes every call's bound parameters into ``~/.iaiops/audit.db``,
and ``audit_forward`` ships those rows to a SIEM. So a parameter that *carries* a
credential (a NATS auth token, a historian password) leaks it twice over unless the
tool declares it in ``sensitive_params``. The mechanism has always existed; what was
missing is anything that notices when a new tool forgets to use it — which is how
``stream_publish`` / ``stream_publish_event`` / ``historian_push`` shipped writing
their credential into the audit row verbatim.

This is the whole-surface counterpart to ``test_audit_param_sanitize.py`` (which
proves the redaction/scrub machinery works on one synthetic tool): here we assert
that every tool which *has* a credential parameter actually uses it. Both front-ends
are covered because HLD §3.1 makes them one audited engine with two boundaries — an
MCP tool and its CLI twin must not disagree about what is a secret.

Name-based detection is deliberately crude. It cannot know a parameter holds a
secret; it can only know the name says so. That asymmetry is the right one: a false
positive costs one line in ``_REFERENCE_NOT_SECRET``, a false negative costs a
credential in a log that leaves the box.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
import typer

from iaiops.cli._root import app as cli_app
from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.policy import get_policy_engine, reset_policy_engine

# Substrings that mark a parameter as carrying a credential value.
_CREDENTIAL_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)

# Parameters whose name matches a hint but which hold a REFERENCE to a credential,
# never the credential itself. Redacting these would blind the audit trail (you
# could no longer tell which stored secret a call used) while protecting nothing.
# Each entry is an exemption that must be justified here, not a suppression list.
_REFERENCE_NOT_SECRET = frozenset(
    {
        # Lookup key into the encrypted store (``iaiops secret set <name>``); the
        # value it resolves to never appears in the tool signature.
        "secret_name",
    }
)


def _undeclared_credentials(name: str, fn: Any) -> list[str]:
    """Parameters of ``fn`` that look like credentials but are not declared."""
    declared = set(getattr(fn, "_sensitive_params", []) or [])
    try:
        params = inspect.signature(inspect.unwrap(fn)).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins have no signature
        return []
    return [
        f"{name}.{param}"
        for param in params
        if param not in _REFERENCE_NOT_SECRET
        and param not in declared
        and any(hint in param.lower() for hint in _CREDENTIAL_HINTS)
    ]


# ── MCP surface ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_mcp_tool_audits_a_credential_in_the_clear(full_tool_registry) -> None:
    assert full_tool_registry, "expected tools to be registered"
    leaks = sorted(
        leak
        for name, tool in full_tool_registry.items()
        for leak in _undeclared_credentials(name, tool.fn)
    )
    assert not leaks, (
        "credential params not declared in sensitive_params — these land in "
        f"audit.db (and any SIEM forward) verbatim: {leaks}"
    )


# ── CLI surface ───────────────────────────────────────────────────────────────


def _all_commands(a: typer.Typer):
    yield from getattr(a, "registered_commands", [])
    for grp in getattr(a, "registered_groups", []):
        yield from _all_commands(grp.typer_instance)


@pytest.mark.unit
def test_no_cli_command_audits_a_credential_in_the_clear() -> None:
    leaks = sorted(
        leak
        for cmd in _all_commands(cli_app)
        if cmd.callback is not None
        for leak in _undeclared_credentials(cmd.callback.__name__, cmd.callback)
    )
    assert not leaks, f"CLI commands auditing a credential in the clear: {leaks}"


@pytest.mark.unit
def test_cli_governance_wrapper_exposes_its_declared_secrets() -> None:
    """The outer denial-handling wrapper must not hide ``_sensitive_params``.

    ``functools.wraps`` copies the ORIGINAL callback's ``__dict__``, so without an
    explicit re-export the declaration made via ``@audit_sensitive`` is invisible
    from outside — redaction still happens, but the test above would pass a command
    that declares nothing. Guards the introspection the contract rests on.
    """
    declaring = [
        cmd.callback.__name__
        for cmd in _all_commands(cli_app)
        if cmd.callback is not None and getattr(cmd.callback, "_sensitive_params", None)
    ]
    assert declaring, (
        "no CLI command exposes _sensitive_params — the governance wrapper is "
        "hiding the declaration, so the credential contract cannot see it"
    )


# ── runtime proof ─────────────────────────────────────────────────────────────


@pytest.fixture
def _isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    reset_engine()
    reset_policy_engine()
    get_engine(tmp_path / "audit.db")
    get_policy_engine(tmp_path / "rules.yaml")
    yield
    reset_engine()
    reset_policy_engine()


@pytest.mark.unit
def test_stream_publish_token_never_reaches_the_audit_row(
    _isolated_audit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end on a real tool: the declaration above must actually redact.

    Only the broker connection is stubbed — the token still travels the real
    ``@governed_tool`` path that binds, redacts and writes the audit row, which is
    the path that leaked. Stubbing keeps this off the network (an unreachable
    ``servers`` would otherwise burn the NATS connect timeout, ~2 minutes on CI).
    The stub *fails*, because a failed publish audits too: that is the shape the
    leak had.
    """
    from mcp_server.tools import egress_tools

    def _no_broker(*_args, **_kwargs):
        raise ConnectionError("stubbed: no broker in this test")

    monkeypatch.setattr(egress_tools, "get_publisher", _no_broker)

    egress_tools.stream_publish(
        points=[{"ref": "t", "value": 1}],
        servers="nats://127.0.0.1:1",
        token="SUPER-SECRET-TOKEN",
    )

    rows = get_engine().query(tool="stream_publish")
    assert rows, "no audit row for stream_publish"
    blob = json.dumps([json.loads(row["params"]) for row in rows])
    assert "SUPER-SECRET-TOKEN" not in blob, f"token leaked into audit row: {blob}"


@pytest.mark.unit
def test_cli_audit_sensitive_marker_actually_redacts(_isolated_audit) -> None:
    """The CLI's declaration path redacts for real, not just in metadata.

    Separate from the introspection guard above: that one proves the declaration is
    *visible*, this one proves it *works*. A synthetic command marked exactly like
    ``iaiops historian push`` — no network, so it exercises the govern pass alone.
    """
    from typer.testing import CliRunner

    from iaiops.cli._common import audit_sensitive
    from iaiops.cli._govern import govern_app

    sub = typer.Typer()

    @sub.command("c")
    @audit_sensitive("password")
    def c(host: str, password: str) -> None:
        pass

    root = typer.Typer()
    root.add_typer(sub, name="probe")
    govern_app(root)

    result = CliRunner().invoke(root, ["probe", "c", "plc1", "SUPER-SECRET-VALUE"])
    assert result.exit_code == 0, result.output

    rows = get_engine().query(tool="c")
    assert rows, "no audit row for the probe command"
    blob = json.dumps([json.loads(row["params"]) for row in rows])
    assert "SUPER-SECRET-VALUE" not in blob, f"password leaked into audit row: {blob}"
    assert "plc1" in blob, "redaction must be scoped to the declared param"
