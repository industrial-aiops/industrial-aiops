"""CRA Annex I Part I(2)(l) asks for an opt-out from activity recording.

The audit trail is the product's governance backbone, so the opt-out is narrow
by design: ``IAIOPS_AUDIT_OPT_OUT=reads`` stops recording **successful
low/medium-risk calls only**. High/critical calls (device writes) are always
recorded and still fail closed when the trail cannot be written; denied and
failed calls are still recorded; and the opt-out itself leaves a row, so the
trail shows from when reads went unrecorded.
"""

from __future__ import annotations

import logging

import pytest

from iaiops.core.governance import audit_opt_out
from iaiops.core.governance.audit import get_engine, reset_engine
from iaiops.core.governance.decorators import governed_tool

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv(audit_opt_out.OPT_OUT_ENV, raising=False)
    reset_engine()
    audit_opt_out.reset_for_tests()
    yield
    reset_engine()
    audit_opt_out.reset_for_tests()


@governed_tool(risk_level="low")
def _read() -> dict:
    """[READ][risk=low] A read by declaration."""
    return {"value": 1}


@governed_tool(risk_level="low")
def _failing_read() -> dict:
    """[READ][risk=low] A read that fails."""
    raise RuntimeError("device unreachable")


@governed_tool(risk_level="high", preview_param="dry_run")
def _write(dry_run: bool = True) -> dict:
    """[WRITE][risk=HIGH] A device write."""
    return {"written": not dry_run}


@governed_tool(risk_level="low", egress=True)
def _ship() -> dict:
    """[READ][risk=low] Tagged READ, but ships data off-box."""
    return {"sent": 1}


@governed_tool(risk_level="low")
def _record_case() -> dict:
    """[WRITE][risk=low] A low-risk local state change."""
    return {"case": 1}


@governed_tool(risk_level="low")
def _untagged() -> dict:
    """No tag — like every CLI command."""
    return {"value": 1}


def _rows(tool: str | None = None) -> list[dict]:
    return [r for r in get_engine().query(limit=200) if tool is None or r["tool"] == tool]


def test_without_the_opt_out_every_read_is_recorded():
    _read()
    _read()
    assert len(_rows("_read")) == 2


def test_the_opt_out_stops_recording_successful_reads(monkeypatch):
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    _read()
    _read()
    assert _rows("_read") == []


def test_the_opt_out_is_itself_recorded_once(monkeypatch):
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    _read()
    _read()
    marks = _rows(audit_opt_out.MARKER_TOOL)
    assert len(marks) == 1
    assert "reads" in marks[0]["params"]


def test_failed_reads_are_still_recorded(monkeypatch):
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    with pytest.raises(RuntimeError):
        _failing_read()
    rows = _rows("_failing_read")
    assert len(rows) == 1 and rows[0]["status"] != "ok"


def test_high_risk_calls_are_always_recorded(monkeypatch):
    """The opt-out never reaches a device write, previewed or applied."""
    from iaiops.core.governance.approvals import record_approval

    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    record_approval("_write", approved_by="shift-lead")
    assert _write(dry_run=False) == {"written": True}
    rows = _rows("_write")
    assert len(rows) == 1 and rows[0]["status"] == "ok"
    assert rows[0]["approved_by"] == "shift-lead"


@pytest.mark.parametrize("value", ["all", "everything", "1", "true", "writes"])
def test_any_other_value_keeps_recording_and_says_so(monkeypatch, caplog, value):
    """Fail toward MORE recording: a typo must not switch the trail off."""
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, value)
    with caplog.at_level(logging.WARNING):
        _read()
    assert len(_rows("_read")) == 1
    assert audit_opt_out.OPT_OUT_ENV in caplog.text


@pytest.mark.parametrize("value", ["", "  ", "off", "none", "0"])
def test_explicit_no_opt_out_values(monkeypatch, caplog, value):
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, value)
    with caplog.at_level(logging.WARNING):
        _read()
    assert len(_rows("_read")) == 1
    assert audit_opt_out.OPT_OUT_ENV not in caplog.text


def test_value_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, " READS ")
    _read()
    assert _rows("_read") == []


def test_status_reports_the_scope(monkeypatch):
    assert audit_opt_out.status()["opted_out"] is False
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    state = audit_opt_out.status()
    assert state["opted_out"] is True
    assert state["scope"] == "reads"
    assert "high" in state["always_recorded"]


def test_the_always_recorded_set_is_the_fail_closed_set():
    from iaiops.core.governance import decorators

    assert tuple(audit_opt_out.ALWAYS_RECORDED_RISK) == tuple(decorators._FAIL_CLOSED_RISK)


def test_the_evidence_bundle_says_reads_were_not_recorded(monkeypatch, tmp_path):
    import json
    import zipfile

    from iaiops.core.governance.evidence import export_evidence_bundle

    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    out = tmp_path / "bundle.zip"
    export_evidence_bundle(out)
    with zipfile.ZipFile(out) as bundle:
        doctor = json.loads(bundle.read("doctor_summary.json"))
    assert doctor["audit_opt_out"]["opted_out"] is True


def test_doctor_says_reads_are_not_recorded(monkeypatch, capsys):
    from iaiops.doctor import _report_audit_opt_out

    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    _report_audit_opt_out()
    assert "NOT recorded" in capsys.readouterr().out


@pytest.mark.parametrize(
    "call",
    [_ship, _record_case, _untagged, lambda: _write(dry_run=True)],
    ids=["egress", "low-risk-write", "untagged", "write-preview"],
)
def test_only_declared_reads_can_go_unrecorded(monkeypatch, call):
    """Review finding H2: the opt-out keyed on effective risk alone, so it also
    silenced egress, low-risk state changes and previews of device writes."""
    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    try:
        call()
    except Exception:  # noqa: BLE001 — a denied preview still writes its row
        pass
    tools = {r["tool"] for r in _rows()} - {audit_opt_out.MARKER_TOOL}
    assert tools, "a non-read call went unrecorded under the read opt-out"


def test_no_registered_egress_or_write_tool_is_eligible(full_tool_registry):
    import inspect

    for name, tool in full_tool_registry.items():
        fn = tool.fn
        ok = audit_opt_out.eligible(
            risk_level=getattr(fn, "_risk_level", "low"),
            egress=bool(getattr(fn, "_egress", False)),
            preview_param=getattr(fn, "_preview_param", None),
            doc=inspect.getdoc(fn),
        )
        if getattr(fn, "_egress", False) or getattr(fn, "_preview_param", None):
            assert not ok, name
    assert not audit_opt_out.eligible(
        risk_level="low",
        egress=True,
        preview_param=None,
        doc=inspect.getdoc(full_tool_registry["historian_push"].fn),
    )


def test_cli_commands_are_never_opted_out(monkeypatch):
    from typer.testing import CliRunner

    from iaiops.cli._root import app

    monkeypatch.setenv(audit_opt_out.OPT_OUT_ENV, "reads")
    CliRunner().invoke(app, ["protocols"])
    recorded = [r for r in _rows() if r["tool"] != audit_opt_out.MARKER_TOOL]
    assert recorded, "a CLI command went unrecorded under the read opt-out"


def test_a_failed_marker_write_is_retried(monkeypatch):
    """Review finding M3: the flag was set before the write and never cleared."""

    class _Broken:
        def __init__(self):
            self.calls = 0

        def log(self, **_kw):
            self.calls += 1
            return False

    broken = _Broken()
    audit_opt_out.mark_once(broken)
    audit_opt_out.mark_once(broken)
    assert broken.calls == 2
    audit_opt_out.mark_once(get_engine())
    assert len(_rows(audit_opt_out.MARKER_TOOL)) == 1
