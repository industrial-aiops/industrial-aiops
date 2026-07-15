---
name: iaiops-factory
description: >-
  Factory edition of iaiops — discrete-manufacturing lines: OPC-UA, Modbus-TCP/RTU,
  Siemens S7comm (S7-300/400/1200/1500), Mitsubishi MC/MELSEC, Omron FINS
  (CS/CJ/CP/NX), Allen-Bradley
  EtherNet/IP (ControlLogix/CompactLogix), EtherCAT (CoE/SOEM), PROFINET (DCP
  discovery), MTConnect (CNC machine tools), IO-Link (master JSON — sensor-level
  visibility), MQTT/Sparkplug B/UNS, plus the
  cross-protocol brain (downtime root-cause, OEE, asset inventory). Use for PLC,
  CNC, servo/drive bus, name-of-station, tag browse, Unified Namespace, or
  production-line troubleshooting tasks. Read-first, MOC-gated writes. Also covers
  Phoenix Contact PLCnext vPLC (via its built-in OPC-UA + Modbus servers).
---

# iaiops-factory — 离散制造 edition（11 协议 + 脑）

启动：`IAIOPS_MCP=factory` / `iaiops-mcp-factory`。PLCnext vPLC 现场用精简
`IAIOPS_MCP=plcnext` / `iaiops-mcp-plcnext`（= opcua+modbus，走 vPLC 内建服务）。
单协议现场直接 `IAIOPS_MCP=<协议>`。EtherCAT 需 extra：`pip install iaiops[ethercat]`；
PROFINET：`pip install iaiops[profinet]`（或 `iaiops[factory]` bundle）；Omron FINS 客户端为 in-repo 纯 stdlib 实现，无需第三方库。

## 工具

### OPC-UA（只读）
- `opcua_server_info` / `opcua_browse` / `opcua_read_node` / `opcua_read_many`
- `opcua_subscribe_sample` `opcua_read_alarms` `opcua_read_history`(HDA)
- `opcua_diagnose_connection` — 连接失败五类归因（证书/策略/认证/网络/配置）
- `opcua_discover_tags` — 自动发现 + 语义资产建模
- `opcua_health_summary` — tag vs 阈值分类；`opcua_anomaly_scan` — 有界统计异常扫描

### Modbus-TCP / Modbus-RTU（本 edition 只读）
- `modbus_read_holding`(FC03) `modbus_read_input`(FC04) `modbus_read_coils`(FC01)
  `modbus_read_discrete`(FC02) — 带解码提示
- `modbus_detect_byte_order` — 自动探测寄存器块字节/字序
- `modbus_list_templates` / `modbus_apply_template` — 厂商寄存器模板 → 命名 tag
- `modbus_health_summary` — 寄存器 vs 阈值分类

### Siemens S7comm（pyS7）
- `s7_cpu_info` `s7_read_area` `s7_read_db` `s7_read_many`
- `s7_write_db` — **[WRITE][HIGH][MOC]** 写 DB 单值（默认 off）

### 三菱 MC（3E；Q/L/iQ）
- `mc_cpu_status` `mc_read_words` `mc_read_bits` `mc_read_many`
- `mc_write_words` — **[WRITE][HIGH][MOC]**（默认 off）
- CC-Link 经主站读（零 CC-Link 硬件，见 docs/CCLINK.md）：`mc_cclink_templates`
  `mc_cclink_link_read`（RX/RY/RWr/RWw 刷新映像，模板默认值 `待核实` per 项目）
  `mc_cclink_network_health`（SB/SW 每站链路诊断：classic SW0080–；IE Field
  SB0049 + SW00B0– + SW00A0– baton pass）

### Omron FINS（in-repo stdlib 客户端；CS/CJ/CP/NX-via-FINS）
- `fins_cpu_info`(0501 CPU 型号/版本) `fins_cpu_status`(0601 运行状态/模式/故障字)
- `fins_read_words`(0101; DM/CIO/W/H/A/EM, ≤500 字) `fins_read_bits`
  `fins_read_many`(单会话批量, ≤20 项)
- `fins_write_words` — **[WRITE][HIGH][MOC]**（0102；默认 off）

### Allen-Bradley EtherNet/IP（pycomm3）
- `eip_controller_info` `eip_list_tags` `eip_read_tag` `eip_read_many`
- `eip_write_tag` — **[WRITE][HIGH][MOC]**（默认 off）

### EtherCAT（pysoem/SOEM；**Linux + root/CAP_NET_RAW + 专用网卡 + 真从站**）
- `ethercat_master_state` `ethercat_slaves` `ethercat_slave_info`
- `ethercat_read_sdo`(CoE SDO 上载) `ethercat_read_pdo`(输入过程映像单帧)
- `ethercat_write_sdo` / `ethercat_set_state` — **[WRITE][HIGH][MOC]**
  （AL-state 切换可 START/STOP 运动；默认 off）

### PROFINET（DCP 发现，layer-2 raw socket；不碰 RT 循环数据）
- `profinet_discover`(IdentifyAll) `profinet_identify_station`
  `profinet_station_params` `profinet_asset_inventory`
- `profinet_dcp_set` — **[WRITE][HIGH][MOC]** 重编址 name/IP（可断 IO 关系；默认 off）

### MTConnect（只读；CNC 机床 agent）
- `mtconnect_probe` `mtconnect_current` `mtconnect_sample` `mtconnect_assets`
- `mtconnect_oee_snapshot` — availability/execution/mode/program（OEE 输入）

### IO-Link（只读；主站 JSON 接口 — 传感器级可见性）
- `iolink_master_info` — 主站身份（/deviceinfo：productcode/serial/hw/sw）
- `iolink_ports` — 有界端口扫描（≤32：mode/status + 在线设备身份）
- `iolink_device_info` — 单端口设备身份（vendorid/deviceid/productname/serial/status）
- `iolink_read_pdin` — 过程数据输入（raw hex + 字节数组；按 IODD 解码）
- `iolink_read_isdu` — ISDU 参数读（iolreadacyclic，index/subindex 有界）
- `iolink_scan` — 主站 + 全端口一次性快照
- 配置 `flavor: iotcore`（ifm IoT-Core POST envelope，默认）或 `rest`
  （plain-REST GET，Balluff/Turck 类）；v1 只读，无写工具

### MQTT / Sparkplug B / UNS（含裸 MQTT）
- `mqtt_read_topic` `sparkplug_decode_payload` `sparkplug_subscribe_sample`
  `sparkplug_node_list`
- `uns_browse` `uns_topic_audit` `uns_schema_drift` `uns_live_audit`
  `sparkplug_live_schema` `uns_live_drift`
- `mqtt_publish` — **[WRITE][HIGH][MOC]**（默认 off）

### 离散制造专属（edition 工具;仅随 factory edition 加载,不进全局脑）
- `changeover_analysis` — **换型/SMED 时长**:换型 = 上个产品末件到下个产品首件的间隔(OEE 可用率
  只汇总、不拆解)。从好件完成流按产品切换测每次换型,排最长、算均值/总换型时间,worst-first,
  每时长引用两端时间戳。纯分析,喂 MES/PLC 好件计数。

### Gateway MES/SCADA 读层（edition 工具；厂商 SCADA/MES 平台 HTTP web API — **只读**）
厂商 SCADA/MES 平台的 **Gateway HTTP/web API** 暴露 MES 侧生产面（模块健康、tag 树、当前值、
活动告警、tag 历史）——这是基座 `opcua` connector 覆盖不到的部分。该平台**同时**跑一个 OPC-UA
server，但那已由 `opcua` connector 处理，本读层**不碰 OPC-UA**。全部**只读**（`risk=low`），
**无任何写工具**——是厂商官方 MCP 模块的受治理/只读补集（差异化在审计/预算/回滚 harness，不在写）。
- `ignition_gateway_status` — 网关/模块健康 + 可达性（Gateway doctor 步；`{gateway, modules[]}`）
- `ignition_tag_browse` — 按 provider/path 浏览 tag 树（`{name, path, type, has_children}`）
- `ignition_tag_read` — 单/多 tag 当前值/质量/时间戳（`{path, value, quality, timestamp}`）
- `ignition_alarm_status` — 活动/已确认告警列表（归一化）
- `ignition_tag_history` — 单 tag 时间窗历史（有界聚合样本 ≤5000）
- API token/key 从加密 secret store 按 key 名取，绝不内联；`flavor`（webdev/gateway：资源路径 +
  字段别名）仅存在于连接器内；确切 API 版本/路径 + live gateway 待核实。

### 跨协议脑（永远随 server 暴露）
- 诊断：`diagnose_dataflow` `downtime_root_cause` `downtime_root_cause_live` `downtime_triage`
  `learn_cause_weights` `historian_health` `alarm_bad_actors` `tag_health`
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
- 程序解读：`plc_program_outline` `plc_program_xref` `plc_program_section` `plc_program_visibility`（解读导出的 ST/AWL/L5X 程序,只读文件,强制引用行号）
- 元：`protocols_supported`

## Workflows

1. **Doctor-first**：`protocols_supported` → `iaiops doctor`（或 `opcua_diagnose_connection`
   之类协议自检）→ 再读数。
2. **Read-first**：browse/list → 单点读 → 批量/采样；"没数据"用 `diagnose_dataflow`，
   停机用 `downtime_root_cause_live`（advisory + 证据链）。
3. **MOC 写**：本 edition 的 8 个写工具（s7/mc/fins/eip/ethercat×2/profinet/mqtt）统一
   `risk=HIGH` + 默认 `dry_run=True` + 改前值 undo + `iaiops approve` 具名审批
   双确认。未经授权绝不写生产控制系统。

## 支持版本矩阵（内部 HLD §8，设计文档不随本仓发布；`待核实` 不得当既成事实）

| 协议 | 库(pin) | 规范/版本 | 覆盖 | 传输 | 自测 |
|---|---|---|---|---|---|
| OPC-UA | `asyncua>=1.0,<2` | OPC UA 1.0x（DA+HA+AC 子集） | 任意合规 Server | opc.tcp | ✅ mock+HDA |
| Modbus-TCP | `pymodbus>=3.5,<4` | App 1.1b3；FC 1/2/3/4（读）；写 FC05/06/15/16 未实现（read-only）；字节序探测+厂商模板 | 任意 TCP 从站 | TCP/502 | ✅ |
| Modbus-RTU | `pymodbus>=3.5,<4` + `pyserial>=3.5` | Modbus serial (RTU) | 串口从站 | RS-485/serial | ✅ socat PTY 真串口链路 verified 2026-07-02；物理 RS-485 待核实 |
| S7comm | `pyS7>=2.8,<3` | ISO-on-TCP (RFC1006) | S7-300/400/1200/1500（后者需开 PUT/GET、关 optimized DB） | TCP/102 | ✅ |
| 三菱 MC | `pymcprotocol>=0.3,<1` | MC/SLMP 3E（1E 待核实） | Q/L/QnA/iQ-R/iQ-L | TCP/UDP | ✅ |
| Omron FINS | in-repo stdlib client（无第三方 pin） | FINS per Omron W227/W342（0101/0102/0501/0601 子集；CS/CJ-mode 区码） | CS/CJ/CP/NX(NJ via FINS) 家族（厂内覆盖 待核实） | UDP 9600（默认）+ FINS/TCP | ✅ in-repo mock responder 验证（tests/test_fins.py）；live PLC 待核实 |
| EtherNet/IP | `pycomm3>=1.2,<2` | EtherNet/IP+CIP, tag-based | AB Logix：ControlLogix/CompactLogix（Micro800/PCCC = roadmap） | TCP/44818 | ✅ |
| EtherCAT | `pysoem>=1.1,<2`（extra） | EtherCAT；CoE SDO/PDO | SOEM 兼容主从 | Linux+root+真从站 | ⚠️ 无软仿真；真机 待核实 |
| PROFINET | `pnio-dcp>=1.1,<3`（extra） | DCP 发现/诊断，**不碰 RT 循环** | 西门子系 PN 站 | L2 raw socket | ✅ mock；真机 待核实 |
| MTConnect | `requests>=2.31,<3` | MTConnect 1.x | CNC/机床（agent） | HTTP REST | ✅ 静态XML |
| IO-Link | `requests>=2.31,<3`（复用 MTConnect pin） | IO-Link Master JSON Integration（IOLINK-JSON）；ifm IoT-Core / plain-REST 双 flavor | 带 JSON/REST 接口的主站（ifm/Balluff/Turck 类） | HTTP REST/JSON | ✅ mock 主站（双 flavor）；live master 待核实 |
| MQTT/Sparkplug B | `paho-mqtt>=2.0,<3` + `protobuf>=4.25,<8` | MQTT 3.1.1/5；SpB(Tahu)；亦支持裸 MQTT | SpB 边缘/Broker；UNS | TCP/1883/8883 | ✅ |
| PLCnext vPLC | 复用 OPC-UA/Modbus pin | 菲尼克斯 PLCnext 内建 OPC-UA(4840)+Modbus-TCP | Phoenix Contact vPLC | opc.tcp+TCP/502 | ✅ 路由验证（`tests/test_plcnext_route.py`）；活体 待核实 |
| Gateway MES/SCADA 读层: WebDev | `requests>=2.31,<3`（复用 MTConnect pin，无新 HTTP 依赖） | Gateway HTTP web API（WebDev 模块 JSON 端点：`/system/webdev/...` — status·tags/browse·tags/read·alarms·tags/history）；**只读**，不碰平台 OPC-UA server（由 opcua connector 覆盖）；确切 API 版本/路径 待核实 | 平台 Gateway 聚合的 provider tag / 告警 / 历史 | HTTPS + token/API-key | ✅ mock 网关（in-repo，双 flavor）；live gateway + 确切 API 版本/路径 待核实 |
| Gateway MES/SCADA 读层: Gateway | `requests>=2.31,<3`（复用 MTConnect pin，无新 HTTP 依赖） | Gateway HTTP web API（内建状态/系统函数 REST：`/data/status`·`/data/tags`·`/data/alarms` 布局）；**只读**，JSON 建模，确切路径树 待核实 | 平台 Gateway 状态/模块/tag/告警/历史 | HTTPS + token/API-key | ✅ mock 网关（in-repo，双 flavor）；live gateway + 确切 API 版本/路径 待核实 |
