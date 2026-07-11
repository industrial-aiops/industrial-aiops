---
name: iaiops-building
description: >-
  Building edition of iaiops — facility / HVAC / BMS / 厂务 over BACnet/IP
  (ASHRAE 135): Who-Is discovery, object/point lists, presentValue snapshots, COV
  capture, TrendLog reads, one MOC-gated property write; plus Modbus-TCP/RTU for
  meters/chillers and optional plain MQTT for IoT sensors, with the
  cross-protocol brain. Use when the task mentions BACnet, BACnet-IP, HVAC, AHU,
  chiller, VAV, BMS, building automation, facility management, 厂务, 楼宇自控,
  Who-Is, presentValue, or TrendLog; also IO-Link masters for smart building
  sensors (JSON interface, read-only). Read-first, MOC-gated writes.
---

# iaiops-building — 楼宇/厂务 edition（BACnet + Modbus + IO-Link + MQTT + 脑）

启动：`IAIOPS_MCP=building` / `iaiops-mcp-building`（= bacnet + modbus + opcua + iolink + 脑）。
IoT 传感器走 MQTT 时叠加：`IAIOPS_MCP=building,sparkplug`。
安装：`pip install iaiops[building]`。BACnet 的 `host` 是**本机** BACnet/IP 接口
（`ip` 或 `ip/mask`）。

## 工具

### BACnet/IP（read-first；暖通/楼宇/厂务）
- `bacnet_discover` — Who-Is：本地 BACnet/IP 网上的设备
- `bacnet_object_list` — 设备的 object/point 列表
- `bacnet_read_property` — 单对象属性（默认 presentValue）
- `bacnet_read_points` — 所有 analog/binary/multistate 点的 presentValue（HVAC 快照）
- `bacnet_cov_subscribe` — 单对象有界 Change-of-Value 捕获
- `bacnet_read_trend_log` — 读设备 TrendLog 缓冲记录
- `bacnet_write_property` — **[WRITE][HIGH][MOC]** 写单对象属性（默认 off：
  `dry_run=True` + 审批双确认；可指挥楼宇设备 — 设定值、输出）

### Modbus-TCP / Modbus-RTU（只读；电表/冷机/表计）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` / `modbus_list_templates` / `modbus_apply_template`
- `modbus_health_summary`

### IO-Link（只读；主站 JSON 接口 — 楼宇智能传感器）
- `iolink_master_info` — 主站身份（/deviceinfo）
- `iolink_ports` — 有界端口扫描（≤32：mode/status + 在线设备身份）
- `iolink_device_info` — 单端口设备身份
- `iolink_read_pdin` — 过程数据输入（raw hex + 字节数组；按 IODD 解码）
- `iolink_read_isdu` — ISDU 参数读（index/subindex 有界）
- `iolink_scan` — 主站 + 全端口一次性快照
- 配置 `flavor: iotcore`（ifm IoT-Core，默认）或 `rest`（plain-REST 主站）；v1 只读

### MQTT（可选叠加 sparkplug 组；IoT 传感器/网关）
- `mqtt_read_topic` — 裸 MQTT 有界收集；`uns_browse` — 主题树浏览
- 完整 Sparkplug B/UNS 工具清单见 **iaiops-factory** skill
- `mqtt_publish` — **[WRITE][HIGH][MOC]**（默认 off）

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live`
  `learn_cause_weights` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis`
  `alarm_rationalization_worksheet`
- 数据质量：`data_quality_scorecard` `data_quality_fleet_rollup`
- 分析：`oee_compute` `downtime_events` `oee_multidim` `monitor_changes`
  `health_summary` (deprecated) `anomaly_scan` (deprecated)
- 资产：`asset_inventory` `cross_protocol_asset_model` `adopt_alias_map` `diff_alias_map`
- 基线：`baseline_learn` `baseline_check` `baseline_record_change` `baseline_status`
  （change-log 基线：拒学薄历史、只报持续越带、每次告警必引基线样本 —— 非黑盒异常检测）
- 合规/信创：`compliance_mapping` `compliance_frameworks` `compliance_dengbao_levels`
  `compliance_report` `compliance_evidence_bundle`
  `historian_push` `export_data` `historian_query` `historian_coverage` `stream_publish` `stream_publish_event` `rca_narrate` `fleet_status` `fleet_incidents`
  `historian_push` `export_data`
- 程序解读：`plc_program_outline` `plc_program_xref` `plc_program_section`（解读导出的 ST/AWL/L5X 程序,只读文件,强制引用行号）
- 元：`protocols_supported`

## Workflows

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → `bacnet_discover`
   （Who-Is 有响应才谈读点）。
2. **Read-first**：`bacnet_object_list` → `bacnet_read_points` 快照 →
   趋势用 `bacnet_read_trend_log`，变化捕获用 `bacnet_cov_subscribe`；
   "没数据"用 `diagnose_dataflow`，坏点排名用 `tag_health`。
3. **MOC 写**：`bacnet_write_property`（与可选 `mqtt_publish`）为
   **[WRITE][HIGH][MOC]**：默认 `dry_run=True`、捕获改前值供 undo、
   `iaiops approve` 具名审批双确认。写设定值可影响在运楼宇设备 ——
   未经授权绝不写。

## 支持版本矩阵（HLD §8；`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| BACnet/IP | `BAC0>=2023.6,<2026`（extra） | ASHRAE 135 Annex J | 暖通/楼宇/厂务控制器 | UDP/47808 | ✅ 读路径 verified 2026-07-02（真 bacpypes3 虚拟设备）；live HVAC 写/COV/trend 待核实 |
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3；FC 1/2/3/4/5/6/15/16 | 电表/冷机/任意 TCP 从站 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口表计 | RS-485/serial | ✅ socat PTY verified 2026-07-02；物理 RS-485 待核实 |
| IO-Link | `requests>=2.31,<3`（复用 MTConnect pin） | IO-Link Master JSON Integration（IOLINK-JSON）；ifm IoT-Core / plain-REST 双 flavor | 带 JSON/REST 接口的主站（ifm/Balluff/Turck 类） | HTTP REST/JSON | ✅ mock 主站（双 flavor）；live master 待核实 |
| MQTT | `paho-mqtt>=2.0,<3` | MQTT 3.1.1/5（裸 MQTT + SpB） | IoT 传感器/网关/Broker | TCP/1883/8883 | ✅ |
