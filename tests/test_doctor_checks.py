"""doctor: plaintext .env in active use is an ERROR; insecure OPC-UA auth warns.

New checks added alongside tests/test_doctor.py (which covers the probe paths).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iaiops import doctor


def _target(**overrides):
    base = dict(
        name="line1",
        protocol="modbus",
        host="10.0.0.5",
        port=502,
        unit_id=1,
        password=lambda: "",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _setup(monkeypatch, tmp_path, targets, *, env_exists: bool):
    env_file = tmp_path / ".env"
    if env_exists:
        env_file.write_text("OT_LINE1_PASSWORD=plain\n")
    monkeypatch.setattr(doctor, "ENV_FILE", env_file)
    monkeypatch.setattr(doctor, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(doctor, "has_store", lambda: False)
    cfg = SimpleNamespace(targets=targets)
    monkeypatch.setattr(doctor, "load_config", lambda *a, **k: cfg)


@pytest.mark.unit
def test_plaintext_env_in_use_is_an_error(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, [_target()], env_exists=True)
    rc = doctor.run_doctor(skip_probe=True)
    out = capsys.readouterr().out
    assert rc == 1  # counted as a problem, not just a warning
    assert "Plaintext .env in use" in out
    assert "iaiops secret migrate" in out


@pytest.mark.unit
def test_no_env_file_is_not_an_error(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, [_target()], env_exists=False)
    rc = doctor.run_doctor(skip_probe=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Plaintext .env" not in out


@pytest.mark.unit
def test_plaintext_env_error_even_with_encrypted_store(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, [_target()], env_exists=True)
    monkeypatch.setattr(doctor, "has_store", lambda: True)
    monkeypatch.setattr(doctor, "check_permissions", lambda: None)
    rc = doctor.run_doctor(skip_probe=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Plaintext .env in use" in out


@pytest.mark.unit
def test_opcua_username_over_unencrypted_channel_warns(monkeypatch, tmp_path, capsys):
    target = _target(
        protocol="opcua",
        endpoint_url="opc.tcp://plc:4840",
        username="operator",
        security_mode="None",
    )
    _setup(monkeypatch, tmp_path, [target], env_exists=False)
    rc = doctor.run_doctor(skip_probe=True)
    out = capsys.readouterr().out
    assert rc == 0  # a warning, not a counted problem
    assert "security_mode" in out
    assert "unencrypted" in out


@pytest.mark.unit
def test_opcua_username_with_signed_channel_no_warning(monkeypatch, tmp_path, capsys):
    target = _target(
        protocol="opcua",
        endpoint_url="opc.tcp://plc:4840",
        username="operator",
        security_mode="SignAndEncrypt",
    )
    _setup(monkeypatch, tmp_path, [target], env_exists=False)
    rc = doctor.run_doctor(skip_probe=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "unencrypted" not in out


@pytest.mark.unit
def test_insecure_auth_helper_ignores_other_protocols():
    target = _target(protocol="modbus", username="operator", security_mode="None")
    assert doctor._opcua_insecure_auth_warning(target) is None


@pytest.mark.unit
def test_insecure_auth_helper_ignores_anonymous_opcua():
    target = _target(protocol="opcua", username="", security_mode="None")
    assert doctor._opcua_insecure_auth_warning(target) is None
