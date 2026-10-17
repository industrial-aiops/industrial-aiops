---
name: iaiops-sensor
description: >-
  Sensor edition of iaiops — connect one industrial sensor and read it correctly:
  draft a sensor profile from a vendor IODD, check it, read one channel once with
  its unit, accuracy band and verification level, then collect. Covers sensors on
  Modbus RTU/TCP (RS-485 / RS-232 / RS-422 / USB serial, 4–20 mA via I/O modules),
  IO-Link masters (JSON interface) and MQTT/Sparkplug nodes. Use when the task
  mentions a sensor, sensor profile, IODD, IO-Link device, process data / pdin,
  decoding registers into engineering units, float32 word order, sentinel /
  no-target values, RS-485 or RS-232 instruments, or "接一个传感器 / 传感器描述 /
  读不懂寄存器 / 单位". Read-only; never writes device or config.
---

# iaiops-sensor — 传感器 edition（Modbus + IO-Link + MQTT/Sparkplug + 传感器工具 + 脑）

启动：`IAIOPS_MCP=sensor` / `iaiops-mcp-sensor`（= modbus + iolink + sparkplug + 传感器工具 + 脑）。
安装：`pip install iaiops[sensor]`（一次拉齐 Modbus / IO-Link / MQTT 依赖）。
设计依据：HLD §16（连得上 / 读得懂 / 采得准）、§17（入口与描述库）。

## 接一个传感器：固定路径

1. **认出设备**：IO-Link 用 `iolink_ports` / `iolink_device_info` 看端口上的 vendor/device id；
   Modbus 设备没有可核对的数字身份 —— 型号由人确认。
2. **拿到描述（profile）**：IO-Link 有 IODD 时用 `sensor_import_iodd` 起草（**返回文本、不写盘**）。
   草稿一律 `verified: 待核实`，IODD 单位代码原样保留 —— 让人把单位改成真实单位。
   Modbus 传感器按规格书写描述（寄存器表、类型、字序、比例、量程、哨兵值）。
3. **检查**：`sensor_profile_check` —— 字段错一个就拒绝并指出是哪个。
4. **绑定（只能由人做）**：Modbus 端点写 `sensor_profile: <文件>`，点位写 `ch:<通道名>`；
   IO-Link 主站写 `port_profiles: {<端口>: <文件>}`，点位写 `port<N>/<通道名>`。
   **不要替用户改 config.yaml**（D51）：把要加的几行给用户，由人贴进去。
5. **试读一次**：`sensor_read_channel` —— 分开报告 `reachable` / `decodable`，读得懂时给出
   值、单位、精度带、描述的核实等级。`untyped: true` 表示裸地址点，按 uint16 读，提醒补类型。
6. **看就绪度**：`site_readiness` —— 「持续采集」下列出未声明类型的点、读不了的点（含原因）、
   仍是 `待核实` 的描述、以及没有单位入库的通道。
7. **采集**：CLI `iaiops collect run <endpoint>`。哨兵 / NaN / 超量程 / 设备不符 / 过程数据长度不符
   都记为**盲区并带原因**，不当读数。

## 工具

### 传感器（只读，edition 模块）
- `sensor_import_iodd` — IODD → 草稿描述文本 + 「未导入」清单；不写盘、不改 config
- `sensor_profile_check` — 校验描述，列出通道 / 布局 / 单位 / 精度带 / 核实等级
- `sensor_read_channel` — 读一个点一次，三级分开报告；读不了的点在联系设备之前就拒绝

### Modbus（只读；RTU 走 RS-485 / RS-232 / USB 串口，TCP 走网口）
- `modbus_read_holding` `modbus_read_input` `modbus_read_coils` `modbus_read_discrete`
- `modbus_detect_byte_order` — float32 / 32 位字序不确定时先探测，**描述里必须写明字序**
- `modbus_health_summary` — 支持带类型的点（`ir:0:float32:CDAB`）与 `ch:` 通道

### IO-Link（只读；主站 JSON 接口）
- `iolink_master_info` `iolink_ports` `iolink_device_info` `iolink_read_pdin` `iolink_read_isdu` `iolink_scan`

### MQTT / Sparkplug（改造用传感节点，如 ESP32）
- `sparkplug_node_list` `sparkplug_subscribe_sample` `mqtt_read_topic` `uns_browse`
- 采集要求端点写 `stale_after_s`（停发和读数不变在线上分不出来）

### 跨协议脑（随 server 暴露）
- `site_readiness` `diagnose_dataflow` `data_quality_scorecard`

## 支持版本

| 路径 | 库 pin | 规范 / 覆盖 | 传输 | 自测 |
|---|---|---|---|---|
| Modbus RTU / TCP | `pymodbus>=3.5,<4`、`pyserial>=3.5` | Modbus Application Protocol；FC03/FC04；16/32 位与 float32 全部字序 | RS-485 / RS-232 / RS-422 / USB 串口；TCP | 进程内假客户端；实验机局域网走查（float32 CDAB、NaN、超量程） |
| IO-Link 主站 | `requests>=2.31,<3` | IO-Link 1.1 过程数据 + IODD 位偏移约定；ifm IoT-Core JSON（其他厂商路径 `待核实`） | HTTP | 进程内模拟主站；实验机局域网走查（哨兵、换传感器、PD 长度） |
| MQTT / Sparkplug | `paho-mqtt>=2.0,<3`、`protobuf>=4.25,<8` | Sparkplug B；纯 MQTT 只有陈旧判断 | TCP / TLS | 真实代理录制回放 |

真实 IO-Link 主站的身份字段编码、真实厂商 IODD 仍 `待核实`。

## 点位写法

| 写法 | 含义 |
|---|---|
| `ch:fz` | Modbus 端点描述里的通道 `fz`（带单位、量程、哨兵） |
| `port2/distance` | IO-Link 主站 2 号口描述里的通道 `distance` |
| `ir:0:float32:CDAB` / `hr:12:int16*0.1` | 带类型的 Modbus 点：表 / 地址 / 类型 / 字序 / 比例（**32 位必须写字序**） |
| `40` | 裸地址：一个保持寄存器按 uint16 读 —— 兼容旧配置，readiness 标「未声明类型」 |

## 边界

- **只读**：不写设备、不做传感器配置（重新示教、改量程不在本 edition）。
- **描述不是背书**：`待核实` 的描述只表示「照资料这样解码」，报告里一直带着这个等级。
- **语义仍由人给**：描述只管「读得懂」，不说哪个通道是产量计数（D16 / D43）。
- 串口 ASCII 仪表（称重仪表、气体分析仪等发文本行的设备）在 HLD §17 E4，**尚未提供**。
