"""Call origin on the audit row: which front-end started a call, and in which mode.

Before this, a row could not say whether an AI agent (over MCP) or someone at the
CLI started a call: both front-ends write ``skill="iaiops"``, and the ``agent``
column is an environment-variable guess (``CLAUDE_CODE`` set in a shell makes a
person at the CLI read as "claude"; an MCP server launched without those variables
reads as "unknown"). These tests pin the replacement:

* ``origin`` — the front-end the call came through: ``mcp`` or ``cli``. Set at the
  front-end boundary, never guessed. A row with no origin (an old row, or a caller
  that is neither front-end) reads ``""`` — unknown, never "human" or "agent".
* ``origin_client`` — the MCP client's self-reported ``clientInfo`` name/version.
* ``origin_session`` — one id per MCP session / per CLI process, to group calls.
* ``write_mode`` — ``preview`` / ``apply`` for tools with a preview flag, else ``""``.

All four are hashed into the chain only when non-empty, so every row written
before this change keeps its hash and an old trail still verifies.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import anyio
import pytest
import typer
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session
from typer.testing import CliRunner

from iaiops.core.governance import origin as origin_mod
from iaiops.core.governance.audit import AuditEngine, compute_row_hash, get_engine
from iaiops.core.governance.decorators import governed_tool

_OLD_FIELDS = (
    "ts",
    "skill",
    "tool",
    "params",
    "result",
    "status",
    "duration_ms",
    "agent",
    "workflow_id",
    "user",
    "risk_level",
    "rationale",
    "approved_by",
    "risk_tier",
    "approver_source",
)


def _old_hash(prev_hash: str, fields: dict) -> str:
    """The row hash exactly as every release up to 0.28.0 computed it."""
    canon = "\x1f".join(str(fields.get(name, "")) for name in _OLD_FIELDS)
    return hashlib.sha256((prev_hash + "\x1f" + canon).encode("utf-8")).hexdigest()


def _rows(tool: str) -> list[dict]:
    return list(reversed(get_engine().query(tool=tool, limit=100)))


# ── chain compatibility ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_a_row_without_origin_hashes_exactly_as_before():
    fields = {name: f"v-{name}" for name in _OLD_FIELDS}
    assert compute_row_hash("p", fields) == _old_hash("p", fields)
    with_empty = {
        **fields,
        "origin": "",
        "origin_client": "",
        "origin_session": "",
        "write_mode": "",
    }
    assert compute_row_hash("p", with_empty) == _old_hash("p", fields)


@pytest.mark.unit
def test_a_row_with_origin_hashes_differently():
    fields = {name: f"v-{name}" for name in _OLD_FIELDS}
    assert compute_row_hash("p", {**fields, "origin": "mcp"}) != _old_hash("p", fields)


def _legacy_db(path) -> None:
    """A 0.28.0-shaped audit.db with two chained rows written by the old code."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "skill TEXT NOT NULL, tool TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}', "
        "result TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'ok', "
        "duration_ms INTEGER NOT NULL DEFAULT 0, agent TEXT NOT NULL DEFAULT 'unknown', "
        "workflow_id TEXT NOT NULL DEFAULT '', user TEXT NOT NULL DEFAULT 'unknown', "
        "risk_level TEXT NOT NULL DEFAULT 'low', rationale TEXT NOT NULL DEFAULT '', "
        "approved_by TEXT NOT NULL DEFAULT '', risk_tier TEXT NOT NULL DEFAULT '', "
        "approver_source TEXT NOT NULL DEFAULT '', prev_hash TEXT NOT NULL DEFAULT '', "
        "row_hash TEXT NOT NULL DEFAULT '')"
    )
    prev = ""
    for i in range(2):
        fields = {name: "" for name in _OLD_FIELDS}
        fields.update(
            ts=f"2026-09-0{i + 1}T00:00:00+00:00",
            skill="iaiops",
            tool=f"old_{i}",
            params="{}",
            result="{}",
            status="ok",
            duration_ms=0,
            agent="claude",
            user="ops",
            risk_level="low",
        )
        row_hash = _old_hash(prev, fields)
        conn.execute(
            f"INSERT INTO audit_log ({', '.join(_OLD_FIELDS)}, prev_hash, row_hash) "  # nosec B608
            f"VALUES ({', '.join('?' * (len(_OLD_FIELDS) + 2))})",
            (*(fields[n] for n in _OLD_FIELDS), prev, row_hash),
        )
        prev = row_hash
    conn.commit()
    conn.close()


@pytest.mark.unit
def test_an_old_trail_migrates_verifies_and_reads_as_unknown_origin(tmp_path):
    db = tmp_path / "audit.db"
    _legacy_db(db)
    engine = AuditEngine(db)
    assert engine.log(skill="iaiops", tool="new_row", origin="cli", origin_session="cli-1")
    assert engine.verify_chain() == {"ok": True, "checked": 3, "unhashed": 0}
    rows = list(reversed(engine.query(limit=10)))
    # The old rows were written by an env-guess "agent" — that guess must not
    # become an origin. They read as unknown.
    assert [r["origin"] for r in rows] == ["", "", "cli"]
    assert rows[0]["agent"] == "claude"


@pytest.mark.unit
@pytest.mark.parametrize(("before", "after"), [("mcp", ""), ("mcp", "cli"), ("", "mcp")])
def test_rewriting_origin_breaks_the_chain(tmp_path, before, after):
    db = tmp_path / "audit.db"
    engine = AuditEngine(db)
    engine.log(skill="iaiops", tool="a", origin=before)
    engine.log(skill="iaiops", tool="b")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE audit_log SET origin = ? WHERE id = 1", (after,))
    conn.commit()
    conn.close()
    result = engine.verify_chain()
    assert not result["ok"] and result["first_broken_id"] == 1


@pytest.mark.unit
@pytest.mark.parametrize("column", ["origin_client", "origin_session", "write_mode"])
def test_rewriting_any_origin_field_breaks_the_chain(tmp_path, column):
    db = tmp_path / "audit.db"
    engine = AuditEngine(db)
    engine.log(
        skill="iaiops",
        tool="a",
        origin="mcp",
        origin_client="client/1",
        origin_session="mcp-x",
        write_mode="apply",
    )
    conn = sqlite3.connect(db)
    conn.execute(f"UPDATE audit_log SET {column} = 'forged' WHERE id = 1")  # nosec B608
    conn.commit()
    conn.close()
    assert not engine.verify_chain()["ok"]


# ── decorator: origin comes from the front-end boundary only ─────────────────


@governed_tool
def _plain_read() -> dict:
    return {"ok": True}


@governed_tool(risk_level="high", preview_param="dry_run")
def _write_tool(value: int, dry_run: bool = True) -> dict:
    return {"applied": not dry_run, "value": value}


@pytest.mark.unit
def test_a_direct_python_call_is_unknown_origin_not_human_or_agent(monkeypatch):
    # Even with an agent marker in the environment, a call that came through
    # neither front-end has no origin. The env guess stays in ``agent`` only.
    monkeypatch.setenv("CLAUDE_CODE", "1")
    _plain_read()
    row = _rows("_plain_read")[-1]
    assert row["origin"] == "" and row["origin_client"] == "" and row["origin_session"] == ""
    assert row["agent"] == "claude"


@pytest.mark.unit
def test_origin_scope_is_recorded_and_does_not_leak():
    scope = origin_mod.CallOrigin(kind="mcp", client="c/1", session="mcp-abc")
    with origin_mod.origin_scope(scope):
        assert origin_mod.current() == scope
        _plain_read()
    assert origin_mod.current() is None
    _plain_read()
    first, second = _rows("_plain_read")[-2:]
    assert (first["origin"], first["origin_client"], first["origin_session"]) == (
        "mcp",
        "c/1",
        "mcp-abc",
    )
    assert second["origin"] == ""


@pytest.mark.unit
def test_origin_kind_is_validated():
    with pytest.raises(ValueError):
        origin_mod.CallOrigin(kind="human", client="", session="")


@pytest.mark.unit
def test_client_text_is_sanitized_and_capped():
    scope = origin_mod.CallOrigin.for_mcp_client(name="evil\x1b[31m" + "x" * 500, version="1\n2")
    assert "\x1b" not in scope.client and "\n" not in scope.client
    assert len(scope.client) <= origin_mod.CLIENT_MAX


@pytest.mark.unit
def test_write_mode_preview_and_apply_and_none(monkeypatch):
    monkeypatch.setenv("OPCUA_AUDIT_APPROVED_BY", "alice")
    _write_tool(1)
    _write_tool(2, dry_run=False)
    _plain_read()
    preview, apply = _rows("_write_tool")[-2:]
    assert (preview["write_mode"], preview["risk_level"]) == ("preview", "low")
    assert (apply["write_mode"], apply["risk_level"], apply["approved_by"]) == (
        "apply",
        "high",
        "alice",
    )
    assert _rows("_plain_read")[-1]["write_mode"] == ""


@pytest.mark.unit
def test_a_denied_write_still_says_apply_and_carries_origin():
    from iaiops.core.governance.decorators import PolicyDenied

    with origin_mod.origin_scope(origin_mod.CallOrigin(kind="mcp", client="c", session="s")):
        with pytest.raises(PolicyDenied):
            _write_tool(3, dry_run=False)
    row = _rows("_write_tool")[-1]
    assert (row["status"], row["write_mode"], row["origin"]) == ("denied", "apply", "mcp")


# ── CLI front-end ────────────────────────────────────────────────────────────


def test_a_cli_command_records_origin_cli_with_a_process_session():
    from iaiops.cli._root import app

    assert CliRunner().invoke(app, ["protocols"]).exit_code == 0
    assert CliRunner().invoke(app, ["protocols"]).exit_code == 0
    rows = _rows("protocols_cmd")[-2:]
    assert [r["origin"] for r in rows] == ["cli", "cli"]
    assert rows[0]["origin_session"].startswith("cli-")
    assert rows[0]["origin_session"] == rows[1]["origin_session"]  # one process
    assert rows[0]["origin_client"] == "iaiops-cli"


def test_a_cli_write_records_preview_and_denied_apply():
    from iaiops.cli._common import write_command
    from iaiops.cli._govern import govern_app

    sub = typer.Typer()

    @sub.command("w")
    @write_command
    def probe_w(value: str, apply: bool = typer.Option(False, "--apply")) -> None:
        return None

    root = typer.Typer()
    root.add_typer(sub, name="probe")
    govern_app(root)
    assert CliRunner().invoke(root, ["probe", "w", "x"]).exit_code == 0
    assert CliRunner().invoke(root, ["probe", "w", "x", "--apply"]).exit_code == 1
    preview, denied = _rows("probe_w")[-2:]
    assert (preview["origin"], preview["write_mode"], preview["status"]) == ("cli", "preview", "ok")
    assert (denied["origin"], denied["write_mode"], denied["status"]) == ("cli", "apply", "denied")


# ── MCP front-end (a real client session, in memory) ─────────────────────────


def _probe_server():
    from mcp_server._shared import _GovernedFastMCP

    server = _GovernedFastMCP("origin-probe")

    @server.tool()
    @governed_tool
    def origin_probe_read() -> dict:
        return {"ok": True}

    @server.tool()
    @governed_tool
    async def origin_probe_async() -> dict:
        return {"ok": True}

    return server


async def _call_twice(server, client_name: str) -> None:
    info = types.Implementation(name=client_name, version="9.9")
    async with create_connected_server_and_client_session(server, client_info=info) as client:
        await client.call_tool("origin_probe_read", {})
        await client.call_tool("origin_probe_async", {})


def test_an_mcp_call_records_origin_mcp_with_client_and_session():
    server = _probe_server()
    anyio.run(_call_twice, server, "probe-agent")
    anyio.run(_call_twice, server, "other-agent")
    reads = _rows("origin_probe_read")
    asyncs = _rows("origin_probe_async")
    assert [r["origin"] for r in reads + asyncs] == ["mcp"] * 4
    assert reads[0]["origin_client"] == "probe-agent/9.9"
    assert reads[1]["origin_client"] == "other-agent/9.9"
    # One session per client connection: same within, different across.
    assert reads[0]["origin_session"] == asyncs[0]["origin_session"]
    assert reads[0]["origin_session"] != reads[1]["origin_session"]
    assert reads[0]["origin_session"].startswith("mcp-")


def test_the_mcp_origin_does_not_outlive_the_call():
    anyio.run(_call_twice, _probe_server(), "probe-agent")
    assert origin_mod.current() is None
    _plain_read()
    assert _rows("_plain_read")[-1]["origin"] == ""


def test_the_forwarded_row_carries_origin(tmp_path):
    """SIEM forward ships whole rows; the new columns must ride along."""
    engine = AuditEngine(tmp_path / "audit.db")
    engine.log(skill="iaiops", tool="t", origin="mcp", origin_client="c/1", write_mode="apply")
    row = engine.rows_after(0)[0]
    assert {k: row[k] for k in ("origin", "origin_client", "write_mode")} == {
        "origin": "mcp",
        "origin_client": "c/1",
        "write_mode": "apply",
    }
    json.dumps(row)  # serialisable as forwarded


# ── the shared MCP helper other servers on the same trail reuse ──────────────


class _FakeInfo:
    name = "fake-client"
    version = "0.1"


class _FakeParams:
    clientInfo = _FakeInfo()  # noqa: N815 — the MCP SDK attribute name


class _FakeSession:
    client_params = _FakeParams()


def test_mcp_origin_from_a_session_is_stable_per_session():
    a, b = _FakeSession(), _FakeSession()
    first, again, other = (
        origin_mod.mcp_origin(a),
        origin_mod.mcp_origin(a),
        origin_mod.mcp_origin(b),
    )
    assert (first.kind, first.client) == ("mcp", "fake-client/0.1")
    assert first.session == again.session != other.session


def test_mcp_origin_without_a_session_is_still_mcp():
    bare = origin_mod.mcp_origin(None)
    assert (bare.kind, bare.client, bare.session) == ("mcp", "", "")
