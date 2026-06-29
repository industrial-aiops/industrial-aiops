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
            "opcua_read_history", "health_summary", "anomaly_scan",
        ],
        "write_tools": [],
        "params": ["endpoint_url", "username", "security_mode", "security_policy"],
    },
    {
        "protocol": "modbus",
        "status": "implemented",
        "library": "pymodbus",
        "transport": "Modbus-TCP",
        "auth": "none (transport)",
        "read_tools": [
            "modbus_read_holding", "modbus_read_input", "modbus_read_coils",
            "modbus_read_discrete", "modbus_health_summary",
        ],
        "write_tools": [],
        "params": ["host", "port(502)", "unit_id"],
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
)

DIAGNOSTICS_TOOLS = ("diagnose_dataflow", "historian_health", "alarm_bad_actors", "tag_health")

# Cross-protocol analytics (read-only): OEE/downtime, active asset inventory, CoV.
ANALYTICS_TOOLS = (
    "oee_compute", "downtime_events", "oee_multidim", "asset_inventory",
    "monitor_changes",
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
        "safety": "Reads non-destructive. Writes (S7/MC/MQTT/EtherNet-IP/EtherCAT) "
        "are HIGH risk_tier, MOC-gated (dry-run + double-confirm + undo capture). "
        "未经授权勿对生产控制系统写入. Preview — not validated against live "
        "PLCs/SCADA; EtherCAT is hardware-only (no simulator) and unverified.",
    }
