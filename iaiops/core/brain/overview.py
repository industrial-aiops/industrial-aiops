"""Self-description: which protocols + capabilities this tool exposes.

A vendor-neutral capability map an agent can read at runtime to decide whether
iaiops is the right tool and which protocol/tool to call.
"""

from __future__ import annotations

# Each protocol: implementation status, library, read tools, write tools (MOC),
# and the connection params its endpoints take.
PROTOCOLS: tuple[dict, ...] = (
    {
        "protocol": "opcua",
        "status": "implemented",
        "library": "asyncua (sync facade)",
        "transport": "opc.tcp binary",
        "auth": "anonymous | username/password (cert security = roadmap)",
        "read_tools": [
            "opcua_server_info", "opcua_browse", "opcua_read_node",
            "opcua_read_many", "opcua_subscribe_sample", "opcua_read_alarms",
            "opcua_read_history", "opcua_diagnose_connection",
            "opcua_discover_tags", "health_summary", "anomaly_scan",
        ],
        "write_tools": [],
        "params": ["endpoint_url", "username", "security_mode", "security_policy"],
        "requirements": "Phoenix Contact PLCnext vPLC (虚拟化 PLC) 覆盖：其内置 OPC-UA "
        "服务器 (opc.tcp 4840) 经此连接器路由验证——in-process asyncua 服务器复现其 "
        "GDS/PLC 地址空间 (tests/test_plcnext_route.py)；便捷 profile: IAIOPS_MCP=plcnext "
        "(opcua+modbus) / iaiops[plcnext]；活体 PLCnext 设备读取仍 待核实。",
    },
    {
        "protocol": "modbus",
        "status": "implemented",
        "library": "pymodbus",
        "transport": "Modbus-TCP + Modbus-RTU (serial)",
        "auth": "none (transport)",
        "read_tools": [
            "modbus_read_holding", "modbus_read_input", "modbus_read_coils",
            "modbus_read_discrete", "modbus_health_summary",
            "modbus_detect_byte_order", "modbus_list_templates", "modbus_apply_template",
        ],
        "write_tools": [],
        "params": [
            "host", "port(502)", "unit_id",
            "transport(tcp|rtu)", "serial_port", "baudrate", "parity", "stopbits", "bytesize",
        ],
        "requirements": "Phoenix Contact PLCnext vPLC (虚拟化 PLC) 覆盖：其 Modbus-TCP "
        "服务器 (用户映射过程数据寄存器) 经此连接器路由验证 (tests/test_plcnext_route.py)；"
        "自带 phoenix_plcnext_process_be 寄存器模板 + IAIOPS_MCP=plcnext profile；"
        "寄存器映射随工程配置，活体 PLCnext 设备读取仍 待核实。"
        "Modbus-RTU live serial verified 2026-07-02 via socat PTY pair + pymodbus RTU "
        "server (tests/test_modbus_rtu_live.py): read_holding/input/coils/discrete round-"
        "trip over real serial framing; not validated against a specific physical RS-485 device.",
    },
    {
        "protocol": "s7",
        "status": "implemented",
        "library": "pyS7 (pure-python, ISO-on-TCP)",
        "transport": "S7comm / RFC1006",
        "auth": "none (CPU PUT/GET gate)",
        "read_tools": ["s7_cpu_info", "s7_read_area", "s7_read_db", "s7_read_many"],
        "write_tools": ["s7_write_db (HIGH/MOC)"],
        "params": ["host", "port(102)", "rack", "slot"],
    },
    {
        "protocol": "mc",
        "status": "implemented",
        "library": "pymcprotocol (pure-python, 3E)",
        "transport": "MELSEC MC 3E binary",
        "auth": "none (transport)",
        "read_tools": ["mc_cpu_status", "mc_read_words", "mc_read_bits", "mc_read_many"],
        "write_tools": ["mc_write_words (HIGH/MOC)"],
        "params": ["host", "port(5007)", "plctype(Q|L|QnA|iQ-R|iQ-L)"],
    },
    {
        "protocol": "mtconnect",
        "status": "implemented",
        "library": "requests + xml.etree",
        "transport": "HTTP REST + XML",
        "auth": "none (read-only by spec)",
        "read_tools": [
            "mtconnect_probe", "mtconnect_current", "mtconnect_sample",
            "mtconnect_assets", "mtconnect_oee_snapshot",
        ],
        "write_tools": [],
        "params": ["agent_url"],
    },
    {
        "protocol": "mqtt",
        "status": "implemented",
        "library": "paho-mqtt",
        "transport": "MQTT 3.1.1/5 (Sparkplug B / UNS)",
        "auth": "username/password + TLS (optional)",
        "read_tools": [
            "mqtt_read_topic", "sparkplug_subscribe_sample",
            "sparkplug_decode_payload", "sparkplug_node_list", "uns_browse",
            "uns_topic_audit", "uns_schema_drift",
            "uns_live_audit", "sparkplug_live_schema", "uns_live_drift",
        ],
        "write_tools": ["mqtt_publish (HIGH/MOC)"],
        "params": ["host/broker", "port(1883/8883)", "topic", "use_tls", "username"],
    },
    {
        "protocol": "ethernetip",
        "status": "implemented",
        "library": "pycomm3 (pure-python, CIP)",
        "transport": "EtherNet/IP (CIP over TCP 44818)",
        "auth": "none (transport); Logix tag model",
        "read_tools": [
            "eip_controller_info", "eip_list_tags", "eip_read_tag", "eip_read_many",
        ],
        "write_tools": ["eip_write_tag (HIGH/MOC)"],
        "params": ["host", "slot", "port(44818)"],
    },
    {
        "protocol": "ethercat",
        "status": "implemented",
        "library": "pysoem / SOEM (OPTIONAL extra: iaiops[ethercat])",
        "transport": "EtherCAT fieldbus (raw Ethernet)",
        "auth": "n/a (physical bus)",
        "read_tools": [
            "ethercat_master_state", "ethercat_slaves", "ethercat_slave_info",
            "ethercat_read_sdo", "ethercat_read_pdo",
        ],
        "write_tools": ["ethercat_write_sdo (HIGH/MOC)", "ethercat_set_state (HIGH/MOC)"],
        "params": ["nic", "expected_slaves"],
        "requirements": "Linux + root/CAP_NET_RAW + dedicated NIC + real slaves; "
        "no software simulator; macOS unsupported; pysoem is an optional extra.",
        "not_supported": "EoE / FoE / SoE = roadmap; no simulator (hardware-only).",
    },
    {
        "protocol": "secsgem",
        "status": "implemented",
        "library": "secsgem (OPTIONAL extra: iaiops[secsgem])",
        "transport": "HSMS (SECS-II over TCP; SEMI E5/E30/E37)",
        "auth": "none (transport); host connects HSMS ACTIVE",
        "read_tools": [
            "secsgem_equipment_status", "secsgem_list_status_variables",
            "secsgem_read_status_variables", "secsgem_list_equipment_constants",
            "secsgem_read_equipment_constants", "secsgem_list_alarms",
            "secsgem_list_process_programs",
        ],
        "write_tools": [],
        "params": ["host", "port(5000)", "unit_id(session/device id)"],
        "requirements": "Semiconductor / display fab equipment with an HSMS port; "
        "secsgem is an optional extra. Preview — not validated against live equipment.",
        "not_supported": "Equipment control (remote commands), recipe upload, and "
        "event/report subscription = out of scope (read-side host only).",
    },
    {
        "protocol": "profinet",
        "status": "implemented",
        "library": "pnio-dcp (OPTIONAL extra: iaiops[profinet])",
        "transport": "PROFINET-DCP (layer-2 raw Ethernet)",
        "auth": "n/a (raw-socket; root/admin/CAP_NET_RAW)",
        "read_tools": [
            "profinet_discover", "profinet_identify_station",
            "profinet_station_params", "profinet_asset_inventory",
        ],
        "write_tools": ["profinet_dcp_set (HIGH/MOC)"],
        "params": ["host (local NIC IP on the PROFINET subnet)"],
        "requirements": "Raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the "
        "PROFINET subnet; pnio-dcp is an optional extra.",
        "not_supported": "RT cyclic process data = out of scope (needs an IO-controller "
        "stack); DCP Set name-of-station/IP is exposed (profinet_dcp_set, HIGH/MOC); "
        "blink/factory-reset = out of scope (physical/destructive).",
    },
    {
        "protocol": "bacnet",
        "status": "implemented",
        "library": "BAC0 / bacpypes3 (OPTIONAL extra: iaiops[bacnet])",
        "transport": "BACnet/IP (UDP 47808)",
        "auth": "none (transport)",
        "read_tools": [
            "bacnet_discover", "bacnet_object_list", "bacnet_read_property",
            "bacnet_read_points", "bacnet_cov_subscribe", "bacnet_read_trend_log",
        ],
        "write_tools": ["bacnet_write_property (HIGH/MOC)"],
        "params": ["host (local BACnet/IP interface, e.g. 10.0.0.5/24)", "port(47808)"],
        "requirements": "Building edition extra. The READ PATH — Who-Is discover + "
        "present-value read + object-list/read-points — is VERIFIED live against a "
        "real bacpypes3 virtual BACnet/IP device on a two-IP subnet in a Linux "
        "container (2026-07-02, tests/test_bacnet_live.py); async BAC0 (2024+) "
        "coroutines are bridged onto a dedicated event loop. Live COV/trend-log "
        "reads + property WRITE on real HVAC gear still 待核实 (not exercised live).",
        "not_supported": "Property writes (present-value with priority/relinquish) are "
        "exposed (bacnet_write_property, HIGH/MOC); object create/delete + file "
        "transfer = out of scope.",
    },
    {
        "protocol": "hart",
        "status": "implemented",
        "library": "hart-protocol (OPTIONAL extra: iaiops[hart])",
        "transport": "HART-IP (UDP/TCP 5094)",
        "auth": "none (transport)",
        "read_tools": [
            "hart_device_identity", "hart_primary_variable", "hart_dynamic_variables",
            "hart_burst_sample",
        ],
        "write_tools": [],
        "params": ["host (HART-IP server/gateway)", "port(5094)"],
        "requirements": "Process edition extra. Command codec verified against "
        "hart-protocol (2026-06-30); the HART-IP wire transport is 待核实 — not "
        "validated against a live HART-IP server/gateway.",
        "not_supported": "Device-specific + write/config commands = not exposed "
        "(OT-dangerous on live instrumentation).",
    },
)

DIAGNOSTICS_TOOLS = (
    "diagnose_dataflow", "historian_health", "alarm_bad_actors", "tag_health",
    "subscription_health", "downtime_root_cause", "downtime_root_cause_live",
    "learn_cause_weights", "data_quality_scorecard", "data_quality_fleet_rollup",
    "heartbeat_health",
)

# Cross-protocol analytics (read-only): OEE/downtime, active asset inventory, CoV.
ANALYTICS_TOOLS = (
    "oee_compute", "downtime_events", "oee_multidim", "asset_inventory",
    "cross_protocol_asset_model", "monitor_changes",
)


def protocols_supported() -> dict:
    """[READ] Capability map: protocols, status, tools, and connection params."""
    implemented = [p for p in PROTOCOLS if p["status"] == "implemented"]
    stubs = [p for p in PROTOCOLS if p["status"] != "implemented"]
    read_count = sum(len(p["read_tools"]) for p in PROTOCOLS)
    write_count = sum(len(p["write_tools"]) for p in PROTOCOLS)
    return {
        "tool": "iaiops",
        "posture": "vendor-neutral, governed, read-first OT data tap + diagnostics",
        "implemented_protocols": [p["protocol"] for p in implemented],
        "roadmap_stubs": [p["protocol"] for p in stubs],
        "protocols": list(PROTOCOLS),
        "diagnostics": list(DIAGNOSTICS_TOOLS),
        "analytics": list(ANALYTICS_TOOLS),
        "tool_counts": {
            "protocol_read": read_count,
            "protocol_write_moc": write_count,
            "diagnostics": len(DIAGNOSTICS_TOOLS),
            "analytics": len(ANALYTICS_TOOLS),
        },
        "safety": "Reads non-destructive. Writes (S7/MC/MQTT/EtherNet-IP/EtherCAT/"
        "PROFINET/BACnet) are HIGH risk_tier, MOC-gated (dry-run + double-confirm + "
        "undo capture). "
        "未经授权勿对生产控制系统写入. Preview — not validated against live "
        "PLCs/SCADA; EtherCAT is hardware-only (no simulator) and unverified.",
    }
