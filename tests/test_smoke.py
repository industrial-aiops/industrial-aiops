"""Smoke tests for the iaiops skeleton.

Proves: every module imports, the CLI Typer app builds and --help works (root +
leaf), the MCP server exposes the expected tools, EVERY MCP tool carries the
iaiops harness marker ``_is_governed_tool``, the config validates protocols,
secrets resolve from the encrypted store, and the EtherCAT stub reports clearly.
"""

import asyncio
import importlib

import pytest
from typer.testing import CliRunner

EXPECTED_TOOLS = {
    # OPC-UA (read / digitalization, incl. Historical Access)
    "opcua_server_info", "opcua_browse", "opcua_read_node", "opcua_read_many",
    "opcua_subscribe_sample", "opcua_read_alarms", "opcua_read_history",
    "opcua_discover_tags",
    # problem surfacing
    "health_summary", "anomaly_scan",
    # Modbus
    "modbus_read_holding", "modbus_read_input", "modbus_read_coils",
    "modbus_read_discrete", "modbus_health_summary",
    "modbus_detect_byte_order", "modbus_list_templates", "modbus_apply_template",
    # S7comm (Siemens / 仿西门子)
    "s7_cpu_info", "s7_read_area", "s7_read_db", "s7_read_many", "s7_write_db",
    # Mitsubishi MC
    "mc_cpu_status", "mc_read_words", "mc_read_bits", "mc_read_many", "mc_write_words",
    # MTConnect (CNC machine tools)
    "mtconnect_probe", "mtconnect_current", "mtconnect_sample", "mtconnect_assets",
    "mtconnect_oee_snapshot",
    # MQTT / Sparkplug B / UNS (full protobuf decode)
    "mqtt_read_topic", "sparkplug_subscribe_sample", "sparkplug_decode_payload",
    "sparkplug_node_list", "uns_browse", "mqtt_publish",
    "uns_topic_audit", "uns_schema_drift",
    "uns_live_audit", "sparkplug_live_schema", "uns_live_drift",
    # EtherNet/IP (Rockwell / Allen-Bradley Logix)
    "eip_controller_info", "eip_list_tags", "eip_read_tag", "eip_read_many",
    "eip_write_tag",
    # EtherCAT (pysoem / SOEM fieldbus — optional extra, hardware-only)
    "ethercat_master_state", "ethercat_slaves", "ethercat_slave_info",
    "ethercat_read_sdo", "ethercat_read_pdo", "ethercat_write_sdo",
    "ethercat_set_state",
    # cross-protocol diagnostics
    "diagnose_dataflow", "historian_health", "alarm_bad_actors", "tag_health",
    "data_quality_fleet_rollup", "learn_cause_weights",
    # cross-protocol analytics (OEE / downtime / asset / CoV)
    "oee_compute", "downtime_events", "oee_multidim", "asset_inventory",
    "cross_protocol_asset_model", "monitor_changes",
    # BACnet/IP (building / HVAC — bounded COV + read-only trend log)
    "bacnet_cov_subscribe", "bacnet_read_trend_log",
    # self-description
    "protocols_supported",
}

# Tools that perform an OT-dangerous write/command — must be governed high-risk.
WRITE_TOOLS = {
    "s7_write_db", "mc_write_words", "mqtt_publish", "eip_write_tag",
    "ethercat_write_sdo", "ethercat_set_state",
}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "iaiops",
        "iaiops.core.runtime.config",
        "iaiops.core.runtime.connection",
        "iaiops.doctor",
        "iaiops.core.runtime.secretstore",
        "iaiops.core.brain._shared",
        "iaiops.connectors.opcua.ops",
        "iaiops.core.brain.analysis",
        "iaiops.connectors.modbus.ops",
        "iaiops.connectors.s7.ops",
        "iaiops.connectors.mc.ops",
        "iaiops.connectors.mtconnect.ops",
        "iaiops.connectors.sparkplug.ops",
        "iaiops.connectors.sparkplug.live",
        "iaiops.connectors.eip.ops",
        "iaiops.core.brain.oee",
        "iaiops.core.brain.asset_inventory",
        "iaiops.core.brain.asset_model",
        "iaiops.core.brain.semantics",
        "iaiops.core.brain.monitor",
        "iaiops.core.brain.diagnostics",
        "iaiops.core.brain.overview",
        "iaiops.connectors.ethercat.ops",
        "iaiops.connectors.sparkplug.sparkplug_b_pb2",
        "iaiops.cli",
        "iaiops.cli._root",
        "iaiops.cli._common",
        "iaiops.cli.opcua",
        "iaiops.cli.modbus",
        "iaiops.cli.s7",
        "iaiops.cli.mc",
        "iaiops.cli.mtconnect",
        "iaiops.cli.mqtt",
        "iaiops.cli.eip",
        "iaiops.cli.ethercat",
        "iaiops.cli.analytics",
        "iaiops.cli.diagnostics",
        "iaiops.cli.secret",
        "iaiops.cli.init",
        "iaiops.cli.doctor",
        "mcp_server.server",
        "mcp_server._shared",
        "mcp_server.tools.opcua_tools",
        "mcp_server.tools.analysis_tools",
        "mcp_server.tools.modbus_tools",
        "mcp_server.tools.s7_tools",
        "mcp_server.tools.mc_tools",
        "mcp_server.tools.mtconnect_tools",
        "mcp_server.tools.sparkplug_tools",
        "mcp_server.tools.eip_tools",
        "mcp_server.tools.oee_tools",
        "mcp_server.tools.asset_tools",
        "mcp_server.tools.asset_model_tools",
        "mcp_server.tools.monitor_tools",
        "mcp_server.tools.diagnostics_tools",
        "mcp_server.tools.overview_tools",
        "mcp_server.tools.ethercat_tools",
        "mcp_server.tools.bacnet_tools",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version():
    import importlib.metadata

    import iaiops

    # __init__ must not drift from the packaged (pyproject) version — and this
    # survives version bumps without a manual edit.
    assert iaiops.__version__ == importlib.metadata.version("iaiops")


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from iaiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("opcua", "modbus", "s7", "mc", "mtconnect", "mqtt", "eip", "ethercat",
                "diag", "analytics", "secret", "init", "doctor", "mcp", "protocols"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    from iaiops.cli import app

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
        ["eip", "--help"], ["ethercat", "--help"], ["analytics", "--help"],
        ["diag", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"
    for cmd in (
        ["opcua", "info", "--help"], ["opcua", "browse", "--help"],
        ["opcua", "read", "--help"], ["opcua", "read-many", "--help"],
        ["opcua", "sample", "--help"], ["opcua", "alarms", "--help"],
        ["opcua", "history", "--help"], ["opcua", "monitor", "--help"],
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
        ["eip", "info", "--help"], ["eip", "tags", "--help"],
        ["eip", "read", "--help"], ["eip", "read-many", "--help"],
        ["eip", "write-tag", "--help"],
        ["ethercat", "master", "--help"], ["ethercat", "slaves", "--help"],
        ["ethercat", "info", "--help"], ["ethercat", "read-sdo", "--help"],
        ["ethercat", "read-pdo", "--help"], ["ethercat", "write-sdo", "--help"],
        ["ethercat", "set-state", "--help"],
        ["analytics", "oee", "--help"], ["analytics", "downtime", "--help"],
        ["analytics", "oee-multidim", "--help"], ["analytics", "asset", "--help"],
        ["analytics", "asset-model", "--help"],
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
    from iaiops.core.runtime.config import TargetConfig

    with pytest.raises(ValueError, match="unsupported protocol"):
        TargetConfig(name="x", protocol="nonexistent-proto")


@pytest.mark.unit
@pytest.mark.parametrize(
    "protocol",
    ["opcua", "modbus", "s7", "mc", "mtconnect", "mqtt", "ethernetip", "ethercat",
     "secsgem", "profinet", "iec104", "dnp3", "iec61850", "bacnet", "hart"],
)
def test_supported_protocols_accepted(protocol):
    from iaiops.core.runtime.config import TargetConfig

    assert TargetConfig(name="x", protocol=protocol).protocol == protocol


@pytest.mark.unit
def test_eip_alias_normalized_to_ethernetip(tmp_path):
    import iaiops.core.runtime.config as cfg

    path = tmp_path / "config.yaml"
    path.write_text("endpoints:\n  - {name: cell5, protocol: eip, host: 10.0.0.9, slot: 0}\n")
    config = cfg.load_config(path)
    assert config.get_target("cell5").protocol == "ethernetip"
    assert config.get_target("cell5").slot == 0


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
    from iaiops.core.brain.overview import protocols_supported

    out = protocols_supported()
    assert set(out["implemented_protocols"]) == {
        "opcua", "modbus", "s7", "mc", "mtconnect", "mqtt", "ethernetip", "ethercat",
        "secsgem", "profinet", "iec104", "dnp3", "iec61850", "bacnet", "hart",
    }
    assert set(out["roadmap_stubs"]) == set()
    assert "asset_inventory" in out["analytics"]
    assert "oee_compute" in out["analytics"]


@pytest.mark.unit
def test_config_per_protocol_fields(tmp_path):
    import iaiops.core.runtime.config as cfg

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
    from iaiops.core.runtime.config import MonitorTag

    tag = MonitorTag(ref="t", warn_high=70, alarm_high=90, warn_low=5, alarm_low=1)
    assert tag.classify(50) == "ok"
    assert tag.classify(75) == "warn"
    assert tag.classify(95) == "alarm"
    assert tag.classify(3) == "warn"
    assert tag.classify(0) == "alarm"


@pytest.mark.unit
def test_config_default_port_per_protocol(tmp_path):
    import iaiops.core.runtime.config as cfg

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
    import iaiops.core.runtime.config as cfg
    import iaiops.core.runtime.secretstore as ss

    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.delenv("OT_LINE1_PASSWORD", raising=False)
    monkeypatch.setenv("IAIOPS_MASTER_PASSWORD", "mpw")
    ss.SecretStore.unlock("mpw").set("line1", "encrypted-plc-pw")

    target = cfg.TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    assert target.password() == "encrypted-plc-pw"


@pytest.mark.unit
def test_config_password_legacy_env_fallback(monkeypatch, tmp_path):
    """Falls back to the legacy OT_<NAME>_PASSWORD env var when no store."""
    import iaiops.core.runtime.config as cfg
    import iaiops.core.runtime.secretstore as ss

    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")  # no store on disk
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.setenv("OT_LINE1_PASSWORD", "legacy-env-pw")

    target = cfg.TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://h:4840")
    assert target.password() == "legacy-env-pw"


@pytest.mark.unit
def test_ethercat_pysoem_is_optional_and_degrades_gracefully(monkeypatch):
    """Without pysoem installed, the EtherCAT builder raises a teaching error
    (never an unguarded ImportError/crash), and the MCP tool returns a clean
    error dict — proving the optional/lazy/graceful-degrade contract."""
    import builtins

    import iaiops.core.runtime.connection as conn
    from iaiops.core.runtime.config import TargetConfig
    from iaiops.core.runtime.connection import OTConnectionError

    real_import = builtins.__import__

    def _no_pysoem(name, *args, **kwargs):
        if name == "pysoem":
            raise ImportError("No module named 'pysoem'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pysoem)
    target = TargetConfig(name="bus1", protocol="ethercat", nic="eth1")
    with pytest.raises(OTConnectionError) as exc:
        conn._build_ethercat_master(target)
    assert "pysoem" in str(exc.value)
    assert "iaiops[ethercat]" in str(exc.value)

    # The MCP tool wraps that into a sanitized error dict (no crash).
    monkeypatch.setattr(builtins, "__import__", real_import)
    monkeypatch.setattr(conn, "_build_ethercat_master",
                        lambda t: (_ for _ in ()).throw(
                            OTConnectionError("pysoem not installed",
                                              protocol="ethercat")))
    from mcp_server.tools import ethercat_tools

    monkeypatch.setattr(ethercat_tools, "_target", lambda e=None: target)
    out = ethercat_tools.ethercat_master_state(endpoint="bus1")
    assert isinstance(out, dict)
    assert "error" in out and "pysoem" in out["error"]


@pytest.mark.unit
def test_ethercat_requires_nic():
    """The EtherCAT builder rejects an endpoint with no NIC (clear teaching error)."""
    import sys
    import types

    import iaiops.core.runtime.connection as conn
    from iaiops.core.runtime.config import TargetConfig
    from iaiops.core.runtime.connection import OTConnectionError

    # Stub pysoem so we reach the NIC check rather than the import guard.
    fake = types.ModuleType("pysoem")
    fake.Master = lambda: object()
    sys.modules["pysoem"] = fake
    try:
        target = TargetConfig(name="bus0", protocol="ethercat")  # no nic
        with pytest.raises(OTConnectionError, match="no NIC"):
            conn._build_ethercat_master(target)
    finally:
        sys.modules.pop("pysoem", None)


@pytest.mark.unit
def test_connection_translates_opcua_errors():
    from iaiops.core.runtime.config import TargetConfig
    from iaiops.core.runtime.connection import OTConnectionError, _translate_opcua

    target = TargetConfig(name="line1", protocol="opcua", endpoint_url="opc.tcp://1.2.3.4:4840")
    err = _translate_opcua(TimeoutError("timed out"), target)
    assert isinstance(err, OTConnectionError)
    assert "1.2.3.4" in str(err)
