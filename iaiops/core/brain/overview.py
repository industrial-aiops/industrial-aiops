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
        "write_tools": [],
        "params": ["host (local NIC IP on the PROFINET subnet)"],
        "requirements": "Raw-socket access (root/admin/CAP_NET_RAW) on the NIC on the "
        "PROFINET subnet; pnio-dcp is an optional extra.",
        "not_supported": "RT cyclic process data = out of scope (needs an IO-controller "
        "stack); DCP Set (set-name/set-ip/blink/factory-reset) = disruptive, not exposed.",
    },
    {
        "protocol": "iec104",
        "status": "implemented",
        "library": "c104 / iec104-python (OPTIONAL extra: iaiops[iec104])",
        "transport": "IEC 60870-5-104 (TCP 2404)",
        "auth": "none (transport)",
        "read_tools": [
            "iec104_connection_info", "iec104_interrogate", "iec104_read_point",
        ],
        "write_tools": [],
        "params": ["host", "port(2404)", "common_address"],
        "requirements": "Energy edition extra. Binding verified against a c104 "
        "loopback link (2026-06-30); live-RTU read still 待核实.",
        "not_supported": "Control direction (C_SC/C_DC/C_RC/setpoints) = not exposed "
        "(OT-dangerous).",
    },
    {
        "protocol": "dnp3",
        "status": "implemented",
        "library": "pydnp3 / opendnp3 (OPTIONAL extra: iaiops[dnp3])",
        "transport": "DNP3 over TCP (20000)",
        "auth": "none (or DNP3-SA, not modelled)",
        "read_tools": ["dnp3_link_status", "dnp3_integrity_poll"],
        "write_tools": [],
        "params": ["host", "port(20000)", "unit_id(outstation)", "master_address"],
        "requirements": "Energy edition extra. PREVIEW — callback-based opendnp3 "
        "binding 待核实 (pydnp3 has no wheel + needs a live outstation; not yet "
        "verifiable in CI). is_online reflects enable(), not live link-state.",
        "not_supported": "Control (CROB / analog output) = not exposed (OT-dangerous).",
    },
    {
        "protocol": "iec61850",
        "status": "implemented",
        "library": "pyiec61850 — libiec61850 SWIG (OPTIONAL extra: iaiops[iec61850])",
        "transport": "IEC 61850 MMS (ISO-on-TCP 102)",
        "auth": "none (transport)",
        "read_tools": [
            "iec61850_device_directory", "iec61850_browse", "iec61850_read",
        ],
        "write_tools": [],
        "params": ["host", "port(102)"],
        "requirements": "Energy edition extra (pyiec61850, linux-only wheel). Driver "
        "symbol surface verified against the real binding (2026-06-30); live-IED "
        "read still 待核实.",
        "not_supported": "Control blocks (Oper / select-before-operate), GOOSE, "
        "Sampled Values = not exposed / out of scope.",
    },
    {
        "protocol": "bacnet",
        "status": "implemented",
        "library": "BAC0 / bacpypes3 (OPTIONAL extra: iaiops[bacnet])",
        "transport": "BACnet/IP (UDP 47808)",
        "auth": "none (transport)",
        "read_tools": [
            "bacnet_discover", "bacnet_object_list", "bacnet_read_property",
            "bacnet_read_points",
        ],
        "write_tools": [],
        "params": ["host (local BACnet/IP interface, e.g. 10.0.0.5/24)", "port(47808)"],
        "requirements": "Building edition extra. BAC0 who_is/read/disconnect surface "
        "verified (2026-06-30); live building/HVAC read still 待核实.",
        "not_supported": "Present-value writes (with priority/relinquish) = not "
        "exposed (live building-control is OT-dangerous).",
    },
)

DIAGNOSTICS_TOOLS = (
    "diagnose_dataflow", "historian_health", "alarm_bad_actors", "tag_health",
    "subscription_health", "downtime_root_cause", "downtime_root_cause_live",
    "data_quality_scorecard", "data_quality_fleet_rollup", "heartbeat_health",
)

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
