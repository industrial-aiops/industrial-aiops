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


def test_opcua_probe_recovers_on_retry(monkeypatch, capsys):
    # first probe fails, but the diagnosis re-connect succeeds (transient blip):
    # report green "recovered", do NOT count a problem or print a red ✗ ok line.
    cfg = SimpleNamespace(targets=[_opcua_target()])
    monkeypatch.setattr(doctor, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(doctor, "_probe", lambda t: (False, "transient blip"))
    monkeypatch.setattr(
        opcua_diag,
        "diagnose_connection",
        lambda t: {"class": "ok", "diagnosis": "Connection succeeded.", "remediation": "—"},
    )

    rc = doctor.run_doctor(skip_probe=False)
    out = capsys.readouterr().out

    assert rc == 0  # recovered → not a counted problem
    assert "recovered on retry" in out
    assert "✗" not in out


def test_diagnose_opcua_never_raises(monkeypatch):
    def _boom(_t):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(opcua_diag, "diagnose_connection", _boom)
    v = doctor._diagnose_opcua(_opcua_target())
    assert v["class"] == "unknown"
    assert v["remediation"]  # still actionable


# ─── new-protocol probes never crash (informational status, not a hard fail) ──


def _probe_target(protocol, **extra):
    return SimpleNamespace(name="ep", protocol=protocol, host="10.0.0.5",
                           nic="", port=0, unit_id=1, **extra)


def test_probe_profinet_success_and_failure(monkeypatch):
    import iaiops.connectors.profinet.ops as pn
    monkeypatch.setattr(pn, "profinet_discover", lambda t: {"station_count": 3})
    ok, detail = doctor._probe_profinet(_probe_target("profinet"))
    assert ok is True and "stations_found=3" in detail

    monkeypatch.setattr(pn, "profinet_discover",
                        lambda t: (_ for _ in ()).throw(RuntimeError("no raw socket")))
    ok, detail = doctor._probe_profinet(_probe_target("profinet"))
    assert ok is False and "no raw socket" in detail


def _raise(msg):
    def _fn(_t):
        raise RuntimeError(msg)
    return _fn


def test_probe_bacnet_success_and_failure(monkeypatch):
    import iaiops.connectors.bacnet.ops as bn
    monkeypatch.setattr(bn, "bacnet_discover", lambda t: {"device_count": 4})
    ok, detail = doctor._probe_bacnet(_probe_target("bacnet"))
    assert ok is True and "devices_found=4" in detail
    monkeypatch.setattr(bn, "bacnet_discover", _raise("bind fail"))
    ok, detail = doctor._probe_bacnet(_probe_target("bacnet"))
    assert ok is False and "bind fail" in detail


def test_probe_hart_success_error_dict_and_exception(monkeypatch):
    """A healthy HART endpoint must have a probe (no more 'No probe implemented'),
    and both failure shapes — error dict and raised exception — report False."""
    import iaiops.connectors.hart.ops as hart_ops

    monkeypatch.setattr(
        hart_ops, "hart_device_identity",
        lambda t: {"manufacturer_id": 0x60, "device_type": 0x99, "device_id": 65536},
    )
    ok, detail = doctor._probe(_probe_target("hart"))
    assert ok is True
    assert "No probe implemented" not in detail
    assert "mfr=96" in detail and "device_id=65536" in detail

    monkeypatch.setattr(
        hart_ops, "hart_device_identity",
        lambda t: {"error": "no HART response (device/gateway unreachable)"},
    )
    ok, detail = doctor._probe(_probe_target("hart"))
    assert ok is False and "no HART response" in detail

    monkeypatch.setattr(hart_ops, "hart_device_identity", _raise("poll timed out"))
    ok, detail = doctor._probe(_probe_target("hart"))
    assert ok is False and "poll timed out" in detail
