---
name: iaiops-renewables
description: >-
  Renewables edition of iaiops — solar PV plants and wind farms: PV inverters /
  string combiners and wind-turbine controllers over Modbus (SUN2000 / Growatt /
  generic wind-turbine templates), plant SCADA over OPC-UA, and MQTT-Sparkplug
  telemetry, plus the cross-protocol brain (PdM, downtime, OEE, alarm) and a
  renewables signature tool pv_performance (underperforming-string detection).
  Use when the task mentions solar / 光伏 / PV / photovoltaic, inverter / 逆变器 /
  组串 / string / combiner, irradiance / 辐照 / POA, wind / 风电 / turbine / 风机 /
  nacelle / pitch / yaw, plant SCADA, performance ratio, soiling / 积灰 / shading /
  遮挡, or 电站. Read-first; this edition's tool surface is read-only.
---

# iaiops-renewables — 光伏 / 风电 edition（Modbus + OPC-UA + Sparkplug + 脑）

启动：`IAIOPS_MCP=renewables` / `iaiops-mcp-renewables`（= modbus + opcua + sparkplug
+ 脑；等价 `IAIOPS_MCP=modbus,opcua,sparkplug`）。典型现场：逆变器/组串汇流箱、风机控制器
走 Modbus,全站 SCADA 走 OPC-UA,遥测经 MQTT-Sparkplug。语义层已含 irradiance / wind_speed /
rotor_speed / pitch / yaw / state_of_charge 等可再生类别(`opcua_discover_tags` 自动归类)。

## 工具

### 可再生专属（edition 工具;仅随 renewables edition 加载,不进全局脑）
- `pv_performance` — **组串/逆变器欠发检测**:算各组串性能比(有 `expected_w` 用之,或
  额定×辐照/1000,否则对全场中位数),低于阈值即 underperforming(积灰/遮挡/熔丝断/组件失效),
  ~0 功率为 offline。worst-first,每比值引用输入。纯分析,喂逆变器/汇流箱 Modbus 或站 SCADA。

### Modbus-TCP / RTU（只读;逆变器、汇流箱、风机控制器、表计）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — 字节/字序自动探测
- `modbus_list_templates` / `modbus_apply_template` — 厂商模板 → 命名 tag
  （可再生模板:`huawei_sun2000_inverter`、`growatt_inverter`、`generic_wind_turbine`;均 `待核实`）
- `modbus_health_summary` — 寄存器 vs 阈值分类

### OPC-UA（只读;全站 SCADA / PLC 网关）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_read_history`(HDA)
- `opcua_diagnose_connection` `opcua_discover_tags` `opcua_health_summary` `opcua_anomaly_scan`

### MQTT-Sparkplug B（可选;电站遥测 / IoT 网关 UNS）
- `sparkplug_node_list` `sparkplug_subscribe_sample` `sparkplug_decode_payload`
- `mqtt_read_topic` `mqtt_publish` `sparkplug_live_schema`
- `uns_browse` `uns_topic_audit` `uns_schema_drift` `uns_live_audit` `uns_live_drift`

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `historian_health` `alarm_bad_actors` `tag_health`
  `subscription_health` `heartbeat_health` `alarm_flood_analysis` `alarm_cascade`
  `alarm_rationalization_worksheet`
- 预测维护：`pdm_forecast` —— 逆变器温升、风机轴承/齿轮箱趋势 + 到限时间
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

1. **Doctor-first**：`protocols_supported` → `iaiops doctor` → OPC-UA 先 `opcua_diagnose_connection`。
2. **欠发排查**：`modbus_apply_template`(`huawei_sun2000_inverter`) 读各组串功率(+辐照) →
   `pv_performance` 排欠发组串 → 结合 `pdm_forecast` 盯逆变器温升趋势。
3. **停机/告警**：`downtime_triage`;风机齿轮箱/轴承劣化用 `pdm_forecast`。
4. **只读**：本 edition 工具表面全只读(逆变器限功率/风机偏航不经本工具下发)。

## 支持版本矩阵（HLD §8;`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3;FC 1/2/3/4/5/6/15/16 | 逆变器/汇流箱/风机/表计 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口从站/表计 | RS-485/serial | ✅ socat PTY;物理 RS-485 待核实 |
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | 全站 SCADA / PLC 网关 | opc.tcp | ✅ mock+HDA |
| MQTT-Sparkplug B | `paho-mqtt>=2.0,<3`（extra） | Sparkplug B 3.0 | 电站遥测 / IoT 网关 UNS | MQTT/1883/8883 | ✅ broker mock |
