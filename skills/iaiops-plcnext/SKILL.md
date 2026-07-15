---
name: iaiops-plcnext
description: >-
  PLCnext / virtualized-PLC edition of iaiops — Phoenix Contact PLCnext Control
  and vPLC (虚拟化 PLC) reached over its built-in OPC-UA server (opc.tcp 4840) and
  Modbus-TCP process-data server, plus the cross-protocol brain (dataflow
  diagnosis, downtime root cause, PdM, OEE, alarm, baseline). A packaging edition
  — no new connector, no PLCnext-vendor SDK: it routes to the standard OPC-UA and
  Modbus tools already shipped. Use when the task mentions PLCnext / PLCnext
  Control / AXC F / vPLC / virtual PLC / 虚拟 PLC / Phoenix Contact controller over
  OPC-UA or Modbus. Read-first; this edition's tool surface is read-only.
---

# iaiops-plcnext — PLCnext / vPLC edition（OPC-UA + Modbus + 脑）

启动：`IAIOPS_MCP=plcnext` / `iaiops-mcp-plcnext`（= opcua + modbus + 脑;等价
`IAIOPS_MCP=opcua,modbus`）。**打包型 edition**:PLCnext Control / vPLC 通过其**内置
OPC-UA server**(opc.tcp 4840)与 **Modbus-TCP 过程数据 server** 读取 —— 不新增 connector、
不依赖 PLCnext 厂商 SDK,直接复用已发布的标准 OPC-UA / Modbus 工具 + 跨协议脑。

## 工具

### OPC-UA（只读;PLCnext 内置 OPC-UA server,opc.tcp 4840）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_read_history`(HDA)
- `opcua_diagnose_connection` — 连接失败归因(证书/策略/认证/网络/配置)
- `opcua_discover_tags` — 自动发现 + 语义资产建模;`opcua_health_summary` 阈值分类;
  `opcua_anomaly_scan` 有界统计异常扫描

### Modbus-TCP（只读;PLCnext 过程数据 server）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — 字节/字序自动探测
- `modbus_list_templates` / `modbus_apply_template` — 厂商寄存器模板 → 命名 tag
- `modbus_health_summary` — 寄存器 vs 阈值分类

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `rca_corpus_from_maintenance` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 预测维护：`pdm_forecast`
- 数据质量：`data_quality_scorecard` `data_quality_fleet_rollup`
- 分析：`oee_compute` `downtime_events` `oee_multidim` `monitor_changes`
- 资产：`asset_inventory` `cross_protocol_asset_model` `adopt_alias_map` `diff_alias_map`
- 基线：`baseline_learn` `baseline_check` `baseline_record_change` `baseline_status`
- 合规/信创：`compliance_mapping` `compliance_frameworks` `compliance_dengbao_levels`
  `compliance_report` `compliance_evidence_bundle`
  `historian_push` `export_data` `historian_query` `historian_coverage` `stream_publish`
  `stream_publish_event` `rca_narrate` `fleet_status` `fleet_incidents`
- 程序解读：`plc_program_outline` `plc_program_xref` `plc_program_section` `plc_program_visibility`
  （解读导出的 ST/AWL/L5X;PLCnext 工程可导出 IEC 61131 ST 文本后离线解读）
- 元：`protocols_supported`

## Workflows

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → `opcua_diagnose_connection`
   (先确认 PLCnext 内置 OPC-UA server 4840 可达、证书/策略匹配)。
2. **Read-first**：过程量走 OPC-UA `opcua_read_many` / Modbus `modbus_read_holding`;
   "没数据"用 `diagnose_dataflow`,停机用 `downtime_triage` / `downtime_root_cause_live`。
3. **只读**:本 edition 工具表面全只读。若需写(输出/设定值),切到含写工具的 profile 并走统一
   MOC:`risk=HIGH` + 默认 `dry_run=True` + 改前值 undo + `iaiops approve` 具名审批双确认。

## 支持版本矩阵（内部 HLD §8，设计文档不随本仓发布;`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | PLCnext 内置 OPC-UA server | opc.tcp/4840 | ✅ mock+HDA;真 PLCnext 待核实 |
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3;FC 1/2/3/4/5/6/15/16 | PLCnext 过程数据 server | TCP/502 | ✅;真 PLCnext 待核实 |
