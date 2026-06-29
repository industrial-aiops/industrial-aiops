"""doctor: a failed OPC-UA probe prints a classified conclusion + fix, not a stack."""

from __future__ import annotations

from types import SimpleNamespace

from iaiops import doctor
from iaiops.connectors.opcua import diagnostics as opcua_diag


def _opcua_target():
    return SimpleNamespace(
        name="line1",
        protocol="opcua",
        endpoint_url="opc.tcp://plc:4840",
        password=lambda: None,
    )


def test_failed_opcua_probe_reports_classified_remediation(monkeypatch, capsys):
    cfg = SimpleNamespace(targets=[_opcua_target()])
    monkeypatch.setattr(doctor, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(doctor, "_probe", lambda t: (False, "raw asyncua error"))
    monkeypatch.setattr(
        opcua_diag,
        "diagnose_connection",
        lambda t: {
            "class": "certificate",
            "diagnosis": "The server rejected this client's certificate.",
            "remediation": "Add the cert to the server trust list.",
        },
    )

    rc = doctor.run_doctor(skip_probe=False)
    out = capsys.readouterr().out

    assert rc == 1  # a failed probe is a counted problem
    assert "certificate" in out  # the class
    assert "trust list" in out  # the remediation, not a raw stack
    assert "raw asyncua error" not in out  # raw probe error is replaced by the verdict


def test_diagnose_opcua_never_raises(monkeypatch):
    def _boom(_t):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(opcua_diag, "diagnose_connection", _boom)
    v = doctor._diagnose_opcua(_opcua_target())
    assert v["class"] == "unknown"
    assert v["remediation"]  # still actionable
