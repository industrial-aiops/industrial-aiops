---
name: iaiops-clinical
description: >-
  Clinical-facility edition of iaiops — hospital / healthcare facilities as a
  distinct vertical from generic building management, with patient-safety framing.
  BACnet/IP BMS (isolation-room pressurization + medical-gas source monitoring),
  Modbus (medical-gas alarm panels / energy meters), OPC-UA (plant SCADA), plus
  the cross-protocol brain. Two signature safety checks: isolation_room_check
  (ASHRAE 170 / CDC negative/positive pressure) and medical_gas_check (NFPA 99 /
  HTM 02-01 O2 / medical air / vacuum source pressures). Use when the task mentions
  hospital, 医院, healthcare facility, clinical, 医疗设施, isolation room / 隔离病房 /
  负压病房 / AII / PE, operating room / OR / 手术室, ICU, medical gas / 医用气体 /
  医疗气体, oxygen / 氧气 / medical vacuum / 医用真空, or NFPA 99. Read-first; this
  edition's tool surface is read-only.
---

# iaiops-clinical — 医疗设施 edition（BACnet + Modbus + OPC-UA + 脑）

启动：`IAIOPS_MCP=clinical` / `iaiops-mcp-clinical`（= bacnet + modbus + opcua + 脑；
等价显式写法 `IAIOPS_MCP=bacnet,modbus,opcua`）。BACnet 需 extra：
`pip install iaiops[bacnet]`。典型现场：楼宇/暖通/隔离房压力走 BACnet BMS,医用气体
报警屏/表计走 Modbus,全院 SCADA 走 OPC-UA。

> **为什么单列 edition**：医院设施科的关注点是**患者安全**(隔离房压力、医用气体),
> 买家/合规(NFPA 99、感控)与普通楼宇物业不同 —— 所以从 `iaiops-building` 升格为独立
> edition。工具复用同一套楼宇/BACnet + 脑,叠加两个临床安全检查。

## 工具

### 临床安全检查（healthcare-facility;纯分析、只读、患者安全导向）
- `isolation_room_check` — 隔离病房压差合规（ASHRAE 170 / CDC：空气传染隔离 AII 负压、
  保护性环境 PE 正压,≥2.5 Pa）。检出 reversed(反向,可上报安全事件)/breach/low_margin,
  worst-first,每项引用读数。读数来自 `bacnet_read_points` 的压差 AI 点或历史库。
- `medical_gas_check` — 医用气体/真空源压力合规（NFPA 99 / HTM 02-01：O2/医用空气/N2O
  ~345–380 kPa、医用真空须够深）。检出 low_pressure / high_pressure / insufficient_vacuum /
  critical,worst-first,引用数值。读数来自 BACnet AI 点或气体报警屏。
- `or_environment_check` — 手术室通风合规（ASHRAE 170 Table 7.1：温度 20–24°C、相对湿度
  20–60%、换气 ≥20 ACH）。逐参数越界即 breach,worst-first,引用数值。读数来自 BACnet/BMS。

### BACnet/IP（read-first;BMS / 暖通 / 压力 / 气体点）
- `bacnet_discover` — Who-Is：本地 BACnet/IP 网上的设备
- `bacnet_object_list` — 设备的 object/point 列表
- `bacnet_read_property` — 单对象属性（默认 presentValue）
- `bacnet_read_points` — 所有 analog/binary/multistate 点的 presentValue（压差/气体压力快照）
- `bacnet_cov_subscribe` — 单对象有界 Change-of-Value 捕获
- `bacnet_read_trend_log` — 读设备 TrendLog 缓冲记录
- `bacnet_write_property` — **[WRITE][HIGH][MOC]** 写单对象属性（默认 `dry_run=True` + 双确认）

### Modbus-TCP / RTU（只读;医用气体报警屏、能耗表）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — 字节/字序自动探测
- `modbus_list_templates` / `modbus_apply_template` — 厂商寄存器模板 → 命名 tag
- `modbus_health_summary` — 寄存器 vs 阈值分类

### OPC-UA（只读;全院 SCADA / PLC 网关）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_read_history`(HDA)
- `opcua_diagnose_connection` — 连接失败归因;`opcua_discover_tags` 语义资产建模;
  `opcua_health_summary` 阈值分类;`opcua_anomaly_scan` 有界统计异常扫描

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 预测维护：`pdm_forecast` —— 制冷/空压/真空泵趋势 + 到限时间
- 数据质量：`data_quality_scorecard` `data_quality_fleet_rollup`
- 分析：`oee_compute` `downtime_events` `oee_multidim` `monitor_changes`
- 资产：`asset_inventory` `cross_protocol_asset_model` `adopt_alias_map` `diff_alias_map`
- 基线：`baseline_learn` `baseline_check` `baseline_record_change` `baseline_status`
- 合规/信创：`compliance_mapping` `compliance_frameworks` `compliance_dengbao_levels`
  `compliance_report` `compliance_evidence_bundle`
  `historian_push` `export_data` `historian_query` `historian_coverage` `stream_publish`
  `stream_publish_event` `rca_narrate` `fleet_status` `fleet_incidents`
- 程序解读：`plc_program_outline` `plc_program_xref` `plc_program_section` `plc_program_visibility`
- 元：`protocols_supported`

## Workflows

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → BACnet 先 `bacnet_discover`。
2. **患者安全巡检**：`bacnet_read_points` 读隔离房压差 AI 点 → `isolation_room_check`;
   读医用气体源压力点 → `medical_gas_check`。两者 worst-first,`reversed`/`critical`
   优先处置。**判定仅为结构性分析,现场 NFPA 99 报警屏/感控为准**。
3. **停机/告警**：设施设备停机用 `downtime_triage`;制冷/真空泵劣化用 `pdm_forecast`。
4. **MOC 写**：本 edition **读优先**;`bacnet_write_property` 为唯一写工具,统一走 MOC:
   `risk=HIGH` + 默认 `dry_run=True` + 改前值 undo + `iaiops approve` 具名审批双确认。
   **绝不对生命安全相关的暖通/气体系统未经授权下发。**

## 支持版本矩阵（内部 HLD §8，设计文档不随本仓发布;`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| BACnet/IP | `BAC0>=2023.6,<2026`（extra,over bacpypes3） | BACnet/IP（read + 单点写） | BMS/暖通/压力/气体点 | UDP/47808 | ⚠️ mock;真 BMS 待核实 |
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3;FC 1/2/3/4/5/6/15/16 | 气体报警屏/表计/任意从站 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口从站/表计 | RS-485/serial | ✅ socat PTY;物理 RS-485 待核实 |
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | 全院 SCADA / PLC 网关 | opc.tcp | ✅ mock+HDA |
