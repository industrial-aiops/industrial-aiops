---
name: iaiops-water
description: >-
  Water-treatment edition of iaiops — waterworks / wastewater plants / pump
  stations: Modbus-TCP/RTU (dosing skids, analyzers, flow meters), OPC-UA
  (plant SCADA / PLC read), HART-IP process instrumentation (pH, turbidity,
  conductivity, level, flow transmitters), plus the cross-protocol brain
  (downtime root-cause, data quality watchdog, OEE). Use when the task mentions
  water treatment, 水处理, 水厂, 污水, pH, 浊度, turbidity, 电导率, conductivity,
  dissolved oxygen, 加药, dosing pump, 泵站, pump station, aeration / 曝气, or
  lift station. Read-first; this edition's tool surface is read-only.
---

# iaiops-water — 水处理 edition（Modbus + OPC-UA + HART + 脑）

启动：`IAIOPS_MCP=water` / `iaiops-mcp-water`（= modbus + opcua + hart + 脑；
等价显式写法 `IAIOPS_MCP=modbus,opcua,hart`）。HART 需 extra：
`pip install iaiops[hart]`。典型现场：加药撬/分析仪走 Modbus，全厂 SCADA 走
OPC-UA，pH/浊度/电导率/液位/流量变送器走 HART（经网关）。

## 工具

### Modbus-TCP / Modbus-RTU（只读；加药撬、分析仪、流量计、泵站 RTU）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — 字节/字序自动探测（分析仪浮点数常见坑）
- `modbus_list_templates` / `modbus_apply_template` — 厂商寄存器模板 → 命名 tag
- `modbus_health_summary` — 寄存器 vs 阈值分类（如 pH 6.5-8.5 带）

### OPC-UA（只读；全厂 SCADA / PLC 网关）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_read_history`(HDA)
- `opcua_diagnose_connection` — 连接失败归因（证书/策略/认证/网络/配置）
- `opcua_discover_tags` — 自动发现 + 语义资产建模（构筑物/工艺段/设备）
- `opcua_health_summary` — tag vs 阈值分类；`opcua_anomaly_scan` — 有界统计异常扫描

### HART-IP（只读；水质/过程变送器，经网关，端口 5094）
- `hart_device_identity` — 通用设备身份（command 0）
- `hart_primary_variable` — 主变量 PV（如 pH 值、NTU）
- `hart_dynamic_variables` — PV/SV/TV/QV + 回路电流（command 3）
- `hart_burst_sample` — 采样 burst 发布的变量

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 数据质量：`data_quality_scorecard` `data_quality_fleet_rollup`（水质仪表重点：
  电极老化 flatline / staleness / 量程外 —— 坏数据绝不静默插值）
- 分析：`oee_compute` `downtime_events` `oee_multidim` `monitor_changes`
  `health_summary` (deprecated) `anomaly_scan` (deprecated)
- 资产：`asset_inventory` `cross_protocol_asset_model` `adopt_alias_map` `diff_alias_map`
- 基线：`baseline_learn` `baseline_check` `baseline_record_change` `baseline_status`
  （change-log 基线：拒学薄历史、只报持续越带、每次告警必引基线样本 —— 非黑盒异常检测）
- 合规/信创：`compliance_mapping` `compliance_frameworks` `compliance_dengbao_levels`
  `compliance_report` `compliance_evidence_bundle`
  `historian_push` `export_data` `historian_query` `historian_coverage` `stream_publish` `stream_publish_event` `rca_narrate` `fleet_status` `fleet_incidents` `pdm_forecast`
  `historian_push` `export_data`
- 程序解读：`plc_program_outline` `plc_program_xref` `plc_program_section`（解读导出的 ST/AWL/L5X 程序,只读文件,强制引用行号）
- 元：`protocols_supported`

## Workflows

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → HART 先
   `hart_device_identity`，OPC-UA 先 `opcua_diagnose_connection`。
2. **Read-first**：水质巡检 = `modbus_apply_template`/`hart_primary_variable` 读
   pH/浊度/电导率 → `opcua_health_summary` 对阈值 → 异常用 `opcua_anomaly_scan`；
   泵站"没数据"用 `diagnose_dataflow`，停机用 `downtime_root_cause_live`。
3. **MOC 写**：本 edition 工具表面**全只读**（加药量/泵启停不经本工具下发）。
   若现场确需写，须切到含写工具的 profile 并走统一 MOC：`risk=HIGH` +
   默认 `dry_run=True` + 改前值 undo + `iaiops approve` 具名审批双确认。
   未经授权绝不写生产控制系统。

## 支持版本矩阵（HLD §8；`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3；FC 1/2/3/4/5/6/15/16 | 分析仪/加药撬/任意 TCP 从站 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口从站（泵站 RTU/表计） | RS-485/serial | ✅ socat PTY verified 2026-07-02；物理 RS-485 待核实 |
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | 任意合规 Server / SCADA | opc.tcp | ✅ mock+HDA |
| HART-IP | `hart-protocol>=2023.6,<2025`（extra） | HART-IP（经网关） | 水质/过程变送器 | UDP/TCP 5094 | ⚠️ codec CI 自测；真机网关 待核实 |
