---
name: iaiops-process
description: >-
  Process-industry edition of iaiops — chemical / pharma / food & beverage / oil &
  gas plants: HART-IP process instrumentation (transmitters, valve positioners,
  loop current), OPC-UA (DCS / gateway read), Modbus-TCP/RTU (skids, analyzers),
  optional MQTT/Sparkplug B UNS, plus the cross-protocol brain (downtime
  root-cause, data quality, OEE). Use when the task mentions HART, HART-IP,
  transmitter, 变送器, valve positioner, process instrumentation, PV/SV/TV/QV,
  loop current, burst mode, DCS tap, or a process plant. Read-first, MOC-gated
  writes.
---

# iaiops-process — 流程工业 edition（HART + Modbus + OPC-UA + 脑）

启动：`IAIOPS_MCP=process` / `iaiops-mcp-process`（= opcua + modbus + hart + 脑）。
现场有 UNS/Sparkplug 时用 `IAIOPS_MCP=process,sparkplug`（sparkplug 工具清单见
**iaiops-factory** skill）。HART 需 extra：`pip install iaiops[hart]`。

## 工具

### HART-IP（只读；过程仪表 — 变送器、阀门定位器，经网关）
`transport` 为 `udp`（默认）或 `tcp`，端口 5094。
- `hart_device_identity` — 通用设备身份（command 0）
- `hart_primary_variable` — 主变量 PV（command 1）：值 + 单位码
- `hart_dynamic_variables` — 动态变量 PV/SV/TV/QV + 回路电流（command 3）
- `hart_burst_sample` — 主动采样 burst 发布的变量；`hart_burst_listen` — 被动监听非请求 burst publish（待核实 per 网关）

### OPC-UA（只读；DCS/网关旁路读取）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_alarm_events`(A&C 带时间戳) `opcua_read_history`(HDA)
- `opcua_diagnose_connection` — 连接失败归因（证书/策略/认证/网络/配置）
- `opcua_discover_tags` — 自动发现 + 语义资产建模
- `opcua_health_summary` — tag vs 阈值分类；`opcua_anomaly_scan` — 有界统计异常扫描

### Modbus-TCP / Modbus-RTU（只读；撬装/分析仪/RTU 从站）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — 字节/字序自动探测
- `modbus_list_templates` / `modbus_apply_template` — 厂商寄存器模板 → 命名 tag
- `modbus_health_summary` — 寄存器 vs 阈值分类

### 流程专属（edition 工具;仅随 process edition 加载,不进全局脑）
- `control_loop_health` — PID 回路诊断:从一段 PV/SP/OP 采样检出**振荡**(PV 反复穿越 SP)、
  **稳态偏差**(PV 长期偏离 SP)、**输出饱和**(OP 压在 0/100%)。给 verdict(saturated>oscillating>
  offset>ok)。非整定器,只分诊哪些回路要看。纯分析,每项引用数值。
- `heat_exchanger_fouling` — **换热器结垢检测**:按四路温度算热侧温度效能 ε=(hot_in−hot_out)/
  (hot_in−cold_in),前后半窗对比;效能低于阈值或下降超阈即 fouling(结垢征兆,先于强制清洗)。
  纯分析,喂 OPC-UA/Modbus/HART 温度点,verdict 引用效能数值。

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `rca_corpus_from_maintenance` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 数据质量：`data_quality_scorecard` `data_quality_fleet_rollup`（流程工业重点：
  staleness / flatline / bad-quality —— 仪表坏数据绝不静默插值喂 AI）
- 分析：`oee_compute` `downtime_events` `oee_multidim` `monitor_changes`
  `health_summary` (deprecated) `anomaly_scan` (deprecated)
- 资产：`asset_inventory` `cross_protocol_asset_model` `adopt_alias_map` `diff_alias_map`
- 基线：`baseline_learn` `baseline_check` `baseline_record_change` `baseline_status`
  （change-log 基线：拒学薄历史、只报持续越带、每次告警必引基线样本 —— 非黑盒异常检测）
- 合规/信创：`compliance_mapping` `compliance_frameworks` `compliance_dengbao_levels`
  `compliance_report` `compliance_evidence_bundle`
  `historian_push` `export_data` `historian_query` `historian_coverage` `stream_publish` `stream_publish_event` `rca_narrate` `fleet_status` `fleet_incidents` `pdm_forecast`
  `historian_push` `export_data`
- 程序解读：`plc_program_outline` `plc_program_xref` `plc_program_section` `plc_program_visibility`（解读导出的 ST/AWL/L5X 程序,只读文件,强制引用行号）
- 元：`protocols_supported`

## Workflows

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → HART 先
   `hart_device_identity` 证明网关链路，OPC-UA 先 `opcua_diagnose_connection`。
2. **Read-first**：仪表读 PV（`hart_primary_variable`）→ 动态变量 → burst；
   回路异常/告警风暴用 `alarm_bad_actors`（ISA-18.2），"没数据"用 `diagnose_dataflow`。
3. **MOC 写**：本 edition 三个协议的工具全部只读（无写表面）。若叠加 sparkplug，
   `mqtt_publish` 为 **[WRITE][HIGH][MOC]**：默认 `dry_run=True` + 改前状态 undo +
   `iaiops approve` 具名审批双确认。未经授权绝不写生产控制系统。

## 支持版本矩阵（内部 HLD §8，设计文档不随本仓发布；`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| HART-IP | `hart-protocol>=2023.6,<2025`（extra） | HART-IP（经网关） | 过程仪表：变送器/阀门定位器 | UDP/TCP 5094 | ⚠️ codec CI 自测；真机网关 待核实 |
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | 任意合规 Server / DCS 网关 | opc.tcp | ✅ mock+HDA |
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3；FC 1/2/3/4/5/6/15/16 | 任意 TCP 从站 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口从站 | RS-485/serial | ✅ socat PTY verified 2026-07-02；物理 RS-485 待核实 |
