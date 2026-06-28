"""Smoke tests for the ot-aiops skeleton.

Proves: every module imports, the CLI Typer app builds and --help works (root +
leaf), the MCP server exposes the expected tools, EVERY MCP tool carries the
ot-aiops harness marker ``_is_governed_tool``, the config validates protocols,
secrets resolve from the encrypted store, and the EtherCAT stub reports clearly.
"""

import asyncio
import importlib

import pytest
from typer.testing import CliRunner

EXPECTED_TOOLS = {
    # OPC-UA (read / digitalization)
    "opcua_server_info", "opcua_browse", "opcua_read_node", "opcua_read_many",
    "opcua_subscribe_sample", "opcua_read_alarms",
    # problem surfacing
    "health_summary", "anomaly_scan",
    # Modbus
    "modbus_read_holding", "modbus_read_input", "modbus_read_coils",
    "modbus_read_discrete", "modbus_health_summary",
    # S7comm (Siemens / 仿西门子)
    "s7_cpu_info", "s7_read_area", "s7_read_db", "s7_read_many", "s7_write_db",
    # Mitsubishi MC
    "mc_cpu_status", "mc_read_words", "mc_read_bits", "mc_read_many", "mc_write_words",
    # MTConnect (CNC machine tools)
    "mtconnect_probe", "mtconnect_current", "mtconnect_sample", "mtconnect_assets",
    "mtconnect_oee_snapshot",
    # MQTT / Sparkplug B / UNS
    "mqtt_read_topic", "sparkplug_subscribe_sample", "sparkplug_node_list",
    "uns_browse", "mqtt_publish",
    # cross-protocol diagnostics
    "diagnose_dataflow", "historian_health", "alarm_bad_actors", "tag_health",
    # self-description
    "protocols_supported",
    # roadmap stubs
    "ethercat_status", "ethernetip_status",
}

# Tools that perform an OT-dangerous write/command — must be governed high-risk.
WRITE_TOOLS = {"s7_write_db", "mc_write_words", "mqtt_publish"}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "ot_aiops",
        "ot_aiops.config",
        "ot_aiops.connection",
        "ot_aiops.doctor",
        "ot_aiops.secretstore",
        "ot_aiops.ops._shared",
        "ot_aiops.ops.opcua_ops",
        "ot_aiops.ops.analysis",
        "ot_aiops.ops.modbus_ops",
        "ot_aiops.ops.s7_ops",
        "ot_aiops.ops.mc_ops",
        "ot_aiops.ops.mtconnect_ops",
        "ot_aiops.ops.sparkplug_ops",
        "ot_aiops.ops.diagnostics",
        "ot_aiops.ops.overview",
        "ot_aiops.ops.ethercat",
        "ot_aiops.ops.ethernetip",
        "ot_aiops.cli",
        "ot_aiops.cli._root",
        "ot_aiops.cli._common",
        "ot_aiops.cli.opcua",
        "ot_aiops.cli.modbus",
        "ot_aiops.cli.s7",
        "ot_aiops.cli.mc",
        "ot_aiops.cli.mtconnect",
        "ot_aiops.cli.mqtt",
        "ot_aiops.cli.diagnostics",
        "ot_aiops.cli.secret",
        "ot_aiops.cli.init",
        "ot_aiops.cli.doctor",
        "mcp_server.server",
        "mcp_server._shared",
        "mcp_server.tools.opcua_tools",
        "mcp_server.tools.analysis_tools",
        "mcp_server.tools.modbus_tools",
        "mcp_server.tools.s7_tools",
        "mcp_server.tools.mc_tools",
        "mcp_server.tools.mtconnect_tools",
        "mcp_server.tools.sparkplug_tools",
        "mcp_server.tools.diagnostics_tools",
        "mcp_server.tools.overview_tools",
        "mcp_server.tools.ethercat_tools",
        "mcp_server.tools.ethernetip_tools",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version():
    import ot_aiops

    assert ot_aiops.__version__ == "0.1.1"


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from ot_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("opcua", "modbus", "s7", "mc", "mtconnect", "mqtt", "diag",
                "secret", "init", "doctor", "mcp", "protocols"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    from ot_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["opcua", "--help"], ["modbus", "--help"], ["secret", "--help"],
        ["init", "--help"], ["doctor", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"
    for cmd in (
        ["opcua", "--help"], ["modbus", "--help"], ["s7", "--help"],
        ["mc", "--help"], ["mtconnect", "--help"], ["mqtt", "--help"],
        ["diag", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"
    for cmd in (
        ["opcua", "info", "--help"], ["opcua", "browse", "--help"],
        ["opcua", "read", "--help"], ["opcua", "read-many", "--help"],
        ["opcua", "sample", "--help"], ["opcua", "alarms", "--help"],
        ["opcua", "health", "--help"], ["opcua", "anomaly", "--help"],
        ["modbus", "holding", "--help"], ["modbus", "input", "--help"],
        ["modbus", "coils", "--help"], ["modbus", "discrete", "--help"],
        ["modbus", "health", "--help"],
        ["s7", "cpu", "--help"], ["s7", "read-db", "--help"],
        ["s7", "read", "--help"], ["s7", "write-db", "--help"],
        ["mc", "cpu", "--help"], ["mc", "words", "--help"],
        ["mc", "bits", "--help"], ["mc", "write-words", "--help"],
        ["mtconnect", "probe", "--help"], ["mtconnect", "current", "--help"],
        ["mtconnect", "sample", "--help"], ["mtconnect", "assets", "--help"],
        ["mtconnect", "oee", "--help"],
        ["mqtt", "read", "--help"], ["mqtt", "nodes", "--help"],
        ["mqtt", "browse", "--help"], ["mqtt", "publish", "--help"],
        ["diag", "dataflow", "--help"], ["diag", "alarms", "--help"],
        ["diag", "tags", "--help"], ["diag", "historian", "--help"],
        ["secret", "set", "--help"], ["secret", "list", "--help"],
        ["secret", "rm", "--help"], ["secret", "migrate", "--help"],
        ["secret", "rotate-password", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    """Every registered tool callable must carry the @governed_tool marker."""
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), (
            f"{name} is not wrapped with @governed_tool (harness marker missing)"
        )


@pytest.mark.unit
def test_unsupported_protocol_rejected():
    from ot_aiops.config import TargetConfig

    with pytest.raises(ValueError, match="unsupported protocol"):
        TargetConfig(name="x", protocol="profinet")


@pytest.mark.unit
@pytest.mark.parametrize("protocol", ["opcua", "modbus", "s7", "mc", "mtconnect", "mqtt"])
def test_supported_protocols_accepted(protocol):
    from ot_aiops.config import TargetConfig

    assert TargetConfig(name="x", protocol=protocol).protocol == protocol


@pytest.mark.unit
def test_write_tools_are_high_risk_and_default_dry_run():
    """Every OT-dangerous write tool is governed high-risk with dry_run default True."""
    import inspect

    from mcp_server import _shared

    tools = _shared.mcp._tool_manager._tools
    for name in WRITE_TOOLS:
        assert name in tools, f"{name} not registered"
        fn = tools[name].fn
        assert getattr(fn, "_risk_level", "") == "high", f"{name} must be risk_level='high'"
        sig = inspect.signature(fn)
        assert sig.parameters["dry_run"].default is True, f"{name} must default dry_run=True"


@pytest.mark.unit
def test_protocols_supported_lists_all():
    from ot_aiops.ops.overview import protocols_supported

    out = protocols_supported()
    assert set(out["implemented_protocols"]) == {"opcua", "modbus", "s7", "mc", "mtconnect", "mqtt"}
    assert set(out["roadmap_stubs"]) == {"ethernetip", "ethercat"}


@pytest.mark.unit
def test_ethernetip_stub_reports_not_implemented():
    from ot_aiops.ops import ethernetip

    out = ethernetip.ethernetip_status()
    assert out["implemented"] is False
    assert out["status"] == "preview-stub"
    assert "pycomm3" in out["message"]


@pytest.mark.unit
def test_config_per_protocol_fields(tmp_path):
    import ot_aiops.config as cfg

    path = tmp_path / "config.yaml"
    path.write_text(
        "endpoints:\n"
        "  - {name: s7a, protocol: s7, host: 10.0.0.1, rack: 0, slot: 1}\n"
        "  - {name: mca, protocol: mc, host: 10.0.0.2, plctype: iQ-R}\n"
        "  - {name: cnc, protocol: mtconnect, agent_url: 'http://h:5000'}\n"
        "  - {name: uns, protocol: mqtt, host: broker, use_tls: true, topic: 'spBv1.0/#'}\n"
    )
    config = cfg.load_config(path)
    assert config.get_target("s7a").port == 102
    assert config.get_target("mca").plctype == "iQ-R"
    assert config.get_target("cnc").agent_url == "http://h:5000"
    mqtt = config.get_target("uns")
    assert mqtt.use_tls is True and mqtt.port == 8883


@pytest.mark.unit
def test_monitor_tag_classifies():
    from ot_aiops.config import MonitorTag

    tag = MonitorTag(ref="t", warn_high=70, alarm_high=90, warn_low=5, alarm_low=1)
    assert tag.classify(50) == "ok"
    assert tag.classify(75) == "warn"
    assert tag.classify(95) == "alarm"
    assert tag.classify(3) == "warn"
    assert tag.classify(0) == "alarm"


@pytest.mark.unit
def test_config_default_port_per_protocol(tmp_path):
    import ot_aiops.config as cfg

    path = tmp_path / "config.yaml"
    path.write_text(
        "endpoints:\n"
        "  - name: line1\n"
        "    protocol: opcua\n"
        "    endpoint_url: opc.tcp://host:4840\n"
        "  - name: plc1\n"
        "    protocol: modbus\n"
        "    host: 10.0.0.5\n"
    )
    config = cfg.load_config(path)
    assert config.get_target("line1").protocol == "opcua"
    assert config.get_target("plc1").port == 502


@pytest.mark.unit
def test_config_password_resolves_from_encrypted_store(monkeypatch, tmp_path):
    """TargetConfig.password() reads the encrypted store (no plaintext env)."""
    import ot_aiops.config as cfg
    import ot_aiops.secretstore as ss

    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.delenv("OT_LINE1_PASSWORD", raising=False)
    monkeypatch.setenv("OT_AIOPS_MASTER_PASSWORD", "mpw")
    ss.SecretStore.unlock("mpw").set("line1", "encrypted-plc-pw")

    target = cfg.TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    assert target.password() == "encrypted-plc-pw"


@pytest.mark.unit
def test_config_password_legacy_env_fallback(monkeypatch, tmp_path):
    """Falls back to the legacy OT_<NAME>_PASSWORD env var when no store."""
    import ot_aiops.config as cfg
    import ot_aiops.secretstore as ss

    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")  # no store on disk
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.setenv("OT_LINE1_PASSWORD", "legacy-env-pw")

    target = cfg.TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    assert target.password() == "legacy-env-pw"


@pytest.mark.unit
def test_ethercat_stub_reports_not_implemented():
    from ot_aiops.ops import ethercat

    out = ethercat.ethercat_status()
    assert out["implemented"] is False
    assert out["status"] == "preview-stub"
    assert "pysoem" in out["message"]


@pytest.mark.unit
def test_connection_translates_opcua_errors():
    from ot_aiops.config import TargetConfig
    from ot_aiops.connection import OTConnectionError, _translate_opcua

    target = TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://1.2.3.4:4840")
    err = _translate_opcua(TimeoutError("timed out"), target)
    assert isinstance(err, OTConnectionError)
    assert "1.2.3.4" in str(err)
