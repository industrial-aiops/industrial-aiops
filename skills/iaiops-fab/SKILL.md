---
name: iaiops-fab
description: >-
  Fab edition of iaiops — semiconductor / display (panel TFT-LCD/OLED) fab
  equipment over SECS/GEM (SEMI E5 SECS-II, E30 GEM, E37 HSMS) plus OPC-UA for the
  equipment's internal control layer, with the cross-protocol brain (downtime
  root-cause copilot, OEE, asset inventory, data quality). Use when the task
  mentions SECS/GEM, SECS-II, HSMS, GEM host, wafer, panel, fab equipment, MES
  equipment interface, SVID, ECID, ALID, PPID / process program, recipe list, or a
  semiconductor / display fab tool. Read-first, MOC-gated writes.
---

# iaiops-fab — 半导体/显示 fab edition（SECS/GEM + OPC-UA + 脑）

启动：`IAIOPS_MCP=fab` / `iaiops-mcp-fab`（暴露 secsgem + opcua + s7 + modbus + 脑）。
安装：`pip install iaiops[fab]`。我们是 **HOST（HSMS ACTIVE）**，设备是 equipment。

> **Fab 分层认知**：一台 fab 设备是两层 —— **MES-facing** 的 SECS/GEM(HSMS) 接口，与
> 设备**内部控制**（PLC，走 OPC-UA/S7/Modbus）。职责不同，别混。S7/Modbus 工具清单见
> **iaiops-factory** skill（fab profile 已同时暴露）。

## 工具

### SECS/GEM（只读；设备 ↔ MES 标准，fab 入场券）
- `secsgem_equipment_status` — 建立 GEM 链路 + Are-You-There（S1F1/F2）
- `secsgem_list_status_variables` — SVID namelist（S1F11/F12）
- `secsgem_read_status_variables` — SVID 值（S1F3/F4）
- `secsgem_list_equipment_constants` — ECID namelist（S2F29/F30）
- `secsgem_read_equipment_constants` — ECID 值（S2F13/F14）
- `secsgem_list_alarms` — 告警表（S5F5/F6）：ALID、ALCD、text
- `secsgem_list_process_programs` — PPID 目录（S7F19/F20）

### OPC-UA（只读；设备内控层 / opc.tcp 端点）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` — 有界采样后返回（绝不死循环）
- `opcua_read_alarms` — best-effort 活动告警/condition
- `opcua_read_history` — HDA 历史读取（[start,end] 窗口）
- `opcua_diagnose_connection` — 连不上时归因（证书/安全策略/认证/防火墙/DNS/端口/配置）
- `opcua_discover_tags` — 自动发现 tag 并建语义资产模型
- `opcua_health_summary` — tag vs 阈值分类；`opcua_anomaly_scan` — 有界统计异常扫描

### Fab / 质量专属（edition 工具;仅随 fab edition 加载,不进全局脑）
- `spc_check` — 统计过程控制:对一段量测序列套用 Western Electric / Nelson 控制图规则
  (越 3σ、2/3 越 2σ、4/5 越 1σ、连续 8 点单侧、6 点趋势),逐条按点索引报违规;给 USL/LSL
  则附 Cp/Cpk。判 in_control / out_of_control。纯分析,每违规引用触发点索引。
- `defect_pareto` — **缺陷帕累托**:按缺陷类别计数排序,算各类占比与累计占比,标出到 80% 线的
  **关键少数**(遏制/改善最有杠杆的类别)。纯分析,喂检验/缺陷记录,每占比引用计数。

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `rca_corpus_from_maintenance` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 数据质量：`data_quality_scorecard` `data_quality_fleet_rollup`
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

1. **Doctor-first**：`protocols_supported` 看配置 → `iaiops doctor` 探活 →
   `secsgem_equipment_status` 确认 GEM 链路（S1F1/F2 通了再谈其他）。
2. **Read-first**：SVID/ECID namelist → 值 → `secsgem_list_alarms`；PLC 层用 OPC-UA
   工具；停机问题直接 `downtime_root_cause_live`（advisory，引用真实信号）。
3. **MOC 写**：本 edition 的 SECS/GEM 与 OPC-UA 工具均只读；fab profile 暴露的写工具
   （如 `s7_write_db`）走统一 MOC：`risk=HIGH` + 默认 `dry_run=True` + 改前值 undo +
   具名审批人 `iaiops approve` 双确认。未经授权绝不写生产设备。

## 支持版本矩阵（内部 HLD §8，设计文档不随本仓发布；`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| SECS/GEM | `secsgem>=0.3,<1` | SECS-II(E5) · GEM(E30) · HSMS(E37/TCP)；SECS-I(E4) 待核实 | 面板/半导体设备 ↔ MES（HOST 侧） | HSMS/TCP | ✅ host+equipment 全软件自测；真机 待核实 |
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集）；FX/TSN 在路线 | 任意合规 Server | opc.tcp | ✅ mock+HDA |
