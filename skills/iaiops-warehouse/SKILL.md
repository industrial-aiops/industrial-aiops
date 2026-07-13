---
name: iaiops-warehouse
description: >-
  Warehouse / intralogistics edition of iaiops — distribution centers, fulfillment,
  material handling: conveyors, sorters, palletizers, AS/RS, and AGV/AMR fleets.
  EtherNet/IP (Allen-Bradley / Rockwell conveyor & sorter PLCs), Profinet (Siemens
  material-handling lines), Modbus (VFDs / energy meters, with conveyor_vfd &
  agv_battery templates), OPC-UA (WMS/WCS gateways), and MQTT-Sparkplug (AMR / IoT
  telemetry) — plus the cross-protocol brain: predictive maintenance (pdm_forecast
  for conveyor-drive bearing/thermal trend), downtime triage, OEE/throughput, and
  alarm analysis. Use when the task mentions warehouse, 仓储, 物流, intralogistics,
  distribution center / DC, fulfillment, conveyor / 输送线, sorter / 分拣, palletizer,
  AS/RS / 立体库, AGV / AMR / 移动机器人, WMS / WCS, or material handling. Read-first;
  this edition's tool surface is read-only.
---

# iaiops-warehouse — 仓储 / 物料搬运 edition（EtherNet/IP + Profinet + Modbus + OPC-UA + Sparkplug + 脑）

启动：`IAIOPS_MCP=warehouse` / `iaiops-mcp-warehouse`（= eip + profinet + modbus + opcua
+ sparkplug + 脑；等价显式写法 `IAIOPS_MCP=eip,profinet,modbus,opcua,sparkplug`）。
EtherNet/IP 需 extra：`pip install iaiops[eip]`。典型现场：输送/分拣 PLC 走
EtherNet/IP(Rockwell) 或 Profinet(Siemens),驱动/表计走 Modbus,WMS/WCS 网关走
OPC-UA,AGV/AMR 与 IoT 传感走 MQTT-Sparkplug。

> **定位**：复用既有跨协议脑的 **PdM（`pdm_forecast`）/ 停机分诊（`downtime_triage`）/
> OEE / 告警** 能力,针对物料搬运资产(输送带电机轴承、分拣驱动、AGV 电池)对症使用,提供
> 物料搬运专用的 Modbus 模板,并带一个 **仓储专属 edition 工具 `line_bottleneck`**
> (瓶颈工位定位;仅随本 edition 加载,不进全局脑)。

## 工具

### EtherNet/IP（Rockwell 输送/分拣 PLC；写=MOC）
- `eip_controller_info` — 控制器身份/状态
- `eip_list_tags` — 控制器 tag 列表
- `eip_read_tag` / `eip_read_many` — 读单/多 tag（输送段状态、分拣计数、速度）
- `eip_write_tag` — **[WRITE][HIGH][MOC]** 写 tag（默认 `dry_run=True` + 改前值 undo + 双确认）

### Profinet（Siemens 物料搬运线）
- `profinet_discover` — DCP 发现网上 IO 设备/station
- `profinet_identify_station` / `profinet_station_params` — station 身份与参数
- `profinet_asset_inventory` — IO 设备资产清单
- `profinet_dcp_set` — **[WRITE][HIGH][MOC]** DCP 设置站名/IP（默认 dry-run + 双确认）

### Modbus-TCP / RTU（只读；VFD 驱动、能耗表、AGV 电池 BMS）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — 字节/字序自动探测（驱动浮点/32 位常见坑）
- `modbus_list_templates` / `modbus_apply_template` — 厂商寄存器模板 → 命名 tag
  （物料搬运模板：`conveyor_vfd` 输送/分拣 VFD 遥测、`agv_battery` AGV/AMR 电池；均 `待核实`）
- `modbus_health_summary` — 寄存器 vs 阈值分类（如驱动温度/电流带）

### OPC-UA（只读；WMS/WCS 网关、线体 SCADA）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_read_history`(HDA)
- `opcua_diagnose_connection` — 连接失败归因（证书/策略/认证/网络/配置）
- `opcua_discover_tags` — 自动发现 + 语义资产建模；`opcua_health_summary` 阈值分类;
  `opcua_anomaly_scan` 有界统计异常扫描

### MQTT-Sparkplug B（可选；AGV/AMR 车队、IoT 传感/网关的 UNS）
- `sparkplug_node_list` `sparkplug_subscribe_sample` `sparkplug_decode_payload`
- `mqtt_read_topic` `mqtt_publish` `sparkplug_live_schema`
- `uns_browse` `uns_topic_audit` `uns_schema_drift` `uns_live_audit` `uns_live_drift`

### 仓储专属（edition 工具;仅随 warehouse edition 加载,不进全局脑）
- `line_bottleneck` — 产线/物料搬运**瓶颈工位定位**(约束理论 TOC:最低吞吐工位即瓶颈,
  设定整线速率;starved/blocked 佐证——瓶颈上游被 blocked、下游被 starved)。纯分析,
  喂 WMS/WCS/MES/PLC 计数的每工位吞吐或节拍,worst-first,每项引用数值。
- `sortation_health` — 分拣机**读码率/无读/误分拣**分析:按每件分拣记录(是否读到条码、
  应分/实分格口)算三率对标,排出误分拣最多的格口(卡阻/映射错)。纯分析,读 WCS/分拣 PLC 事件。

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 预测维护：`pdm_forecast` —— 输送带电机轴承/温升、分拣驱动、AGV 电池的趋势 + 到限时间
  （早于 `baseline_check` 的越带告警;喂 `conveyor_vfd`/`agv_battery` 模板读出的温度/电流）
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

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → EtherNet/IP 先
   `eip_controller_info`,OPC-UA 先 `opcua_diagnose_connection`。
2. **输送带 PdM**：`modbus_apply_template`(`conveyor_vfd`) 读 drive_temperature /
   motor_current 序列 → `pdm_forecast(warn_high=...)` 估到限时间 → `imminent/degrading`
   即提前派维护。AGV 车队同理用 `agv_battery` 模板 + `pdm_forecast` 盯 SOC/温度衰减。
3. **停机分诊**：分拣线停机 = `downtime_triage`(告警 cascade + RCA + PdM 前兆一次给出),
   或 `downtime_root_cause_live` 现采证据链;吞吐掉速用 OEE/`oee_multidim` 定位瓶颈工位。
4. **MOC 写**：本 edition **读优先**;EtherNet/IP `eip_write_tag`、Profinet `profinet_dcp_set`
   为写工具,统一走 MOC:`risk=HIGH` + 默认 `dry_run=True` + 改前值 undo + `iaiops approve`
   具名审批双确认。未经授权绝不写生产控制系统。

## 支持版本矩阵（内部 HLD §8，设计文档不随本仓发布;`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| EtherNet/IP | `pycomm3>=1.2,<2`（extra） | CIP / EtherNet/IP；Logix tags | Allen-Bradley/Rockwell ControlLogix/CompactLogix | TCP/44818 | ⚠️ mock；真 PLC 待核实 |
| Profinet | `pnio-dcp>=1.1,<3`（extra） | PN-DCP（发现/命名） | 现场 IO 设备/station | Ethernet(raw)/UDP | ⚠️ 发现层自测;真设备 待核实 |
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3；FC 1/2/3/4/5/6/15/16 | VFD/能耗表/AGV BMS/任意从站 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口从站/表计 | RS-485/serial | ✅ socat PTY;物理 RS-485 待核实 |
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | WMS/WCS 网关 / SCADA | opc.tcp | ✅ mock+HDA |
| MQTT-Sparkplug B | `paho-mqtt>=2.0,<3`（extra） | Sparkplug B 3.0 | AGV/AMR / IoT 网关 UNS | MQTT/1883/8883 | ✅ broker mock |
