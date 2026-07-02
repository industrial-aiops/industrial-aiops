---
name: iaiops
description: >-
  Vendor-neutral, governed industrial/OT data tap + intelligent troubleshooting.
  Read (and, gated, write) PLCs, controllers, machine tools and IIoT brokers over
  OPC-UA, Modbus-TCP, Siemens S7comm, Mitsubishi MC, Omron FINS, MTConnect,
  MQTT/Sparkplug B,
  Allen-Bradley EtherNet/IP, EtherCAT (pysoem/SOEM), SECS/GEM (semiconductor /
  display fab equipment over HSMS), PROFINET (DCP discovery), the building edition
  (BACnet/IP), and Phoenix Contact PLCnext vPLC — plus cross-protocol diagnostics
  ("no-data" dataflow diagnosis, OPC-UA connection self-diagnosis, subscription
  health, ISA-18.2 alarm bad-actors, tag/historian health, and the AI downtime
  root-cause copilot) and analytics (OEE/downtime, asset inventory, OPC-UA HDA,
  change-of-value). Use when the task names any industrial protocol, a
  PLC/SCADA/HMI/historian/CNC/RTU/IED, a semiconductor/display fab or SECS/GEM
  equipment, an electrical substation, an opc.tcp:// or mqtt:// endpoint,
  OEE/downtime, downtime root-cause, or OT asset inventory. Routes to
  the iaiops MCP server. Read-first; writes are MOC-gated (high risk, dry-run +
  double-confirm). Do NOT use for IT/network gear, Kubernetes, hypervisors, or
  backups — those are separate AIops tools.
---

# iaiops — ROUTER（识别现场 → 派发 edition skill + MCP profile）

这是**路由 skill**，本身不含工具表。识别任务的行业/协议 → 转到对应 **edition skill**
（工具清单、workflow、支持版本矩阵都在那边），并用对应 profile 启动 MCP（`IAIOPS_MCP=<x>`
环境变量，或等价 sugar 脚本 `iaiops-mcp-<x>`）。现场只暴露 1-2 个协议 + 跨协议脑，
单会话工具 ~15-30，模型不被淹。

## 路由表（关键词 → edition skill → MCP profile）

| 任务提到 | edition skill | MCP profile / entrypoint |
|---|---|---|
| SECS/GEM · SECS-II · HSMS · 半导体/显示 fab · wafer · panel · MES equipment · SVID/ECID · recipe | **iaiops-fab** | `IAIOPS_MCP=fab` / `iaiops-mcp-fab` |
| 离散制造产线 · PLC（S7/S7-1200/1500 · 三菱/MELSEC · Allen-Bradley/ControlLogix/CompactLogix · Omron/FINS/SYSMAC CS/CJ/CP/NX）· Modbus · EtherCAT/CoE/SOEM · PROFINET/DCP · MTConnect/CNC 机床 · Sparkplug B/UNS | **iaiops-factory** | `IAIOPS_MCP=factory` / `iaiops-mcp-factory` |
| 流程工业（化工/制药/食品饮料）· HART/HART-IP · 变送器/阀门定位器 · 过程仪表 · DCS 旁路读取 | **iaiops-process** | `IAIOPS_MCP=process` / `iaiops-mcp-process`（有 UNS 时 `IAIOPS_MCP=process,sparkplug`） |
| BACnet/BACnet-IP · HVAC/暖通 · BMS/楼宇自控 · 厂务/facility · Who-Is · TrendLog | **iaiops-building** | `IAIOPS_MCP=building` / `iaiops-mcp-building` |
| 水处理/水厂 · pH · 浊度/turbidity · 电导率/conductivity · 加药/dosing · 泵站/pump station · 曝气 | **iaiops-water** | `IAIOPS_MCP=water` / `iaiops-mcp-water` |
| Phoenix Contact PLCnext / vPLC（虚拟化 PLC，走内建 OPC-UA + Modbus-TCP） | **iaiops-factory** | `IAIOPS_MCP=plcnext` / `iaiops-mcp-plcnext` |

- 单协议深用（只有一种设备）：直接 `IAIOPS_MCP=opcua`（或 modbus/s7/mc/fins/eip/mtconnect/
  sparkplug/ethercat/secsgem/profinet/bacnet/hart），等价脚本 `iaiops-mcp-<协议>`。
- 跨行业只问 OEE/停机根因/资产盘点/数据质量：任一 profile 均可 —— 跨协议脑
  （诊断/OEE/资产/合规）**默认随 server 暴露**，选覆盖现场协议的 profile 即可；
  纯脑场景可用 `IAIOPS_MCP=brain` / `iaiops-mcp-brain`（只暴露脑，零协议）。
- 说不清行业但报了协议名：按协议列选含它的最小 profile；都不沾 → `iaiops doctor` +
  `protocols_supported` 先看现场配置了什么。

## 部署（0.10.0 起：无默认，必须选菜单）

- **裸启动 `iaiops-mcp`（不设 `IAIOPS_MCP`）不再暴露全部工具**：打印选择菜单到
  stderr 并 exit 2。必须设 `IAIOPS_MCP=<selection>` 或用预置入口 `iaiops-mcp-<name>`。
  `IAIOPS_MCP=menu` 显式打印同一菜单（带各 selection 工具数）后退出。
- `IAIOPS_MCP=all` 仍可**显式**使用（power user；>60 工具时启动日志给洪泛警告）。
- **多进程站点（1 脑 + N 协议）**：跑一个 `iaiops-mcp-brain`（只脑），协议 server 各自
  加 `IAIOPS_MCP_NO_BRAIN=1`（如 `IAIOPS_MCP_NO_BRAIN=1 iaiops-mcp-opcua`）去掉脑，
  避免跨 server 工具重名；`protocols_supported`（发现工具）在 NO_BRAIN 下仍然保留。

## Energy 协议 → 另一个包（不在本 server）

IEC 60870-5-104 / IEC-104、DNP3 / outstation、IEC 61850 / MMS / IED、变电站/
substation、电力/能源/utility SCADA → 用独立的 **iaiops-energy**
（`pip install iaiops-energy`，然后 `iaiops-energy-mcp`；
github.com/industrial-aiops/industrial-aiops-energy）。它复用本包的 core + 脑；
monitor-direction only。**不要**尝试用本 server 的 profile 覆盖能源协议。

## 安全不变量（所有 edition 一致，路由前先记住）

- **Read-first**：默认只读；先 `protocols_supported` 看能力、`iaiops doctor` /
  `<protocol> doctor` 验链路，再谈读，最后才谈写。
- **写 = MOC（Management-of-Change）**：The 9 write tools（`s7_write_db`、
  `mc_write_words`、`fins_write_words`、`mqtt_publish`、`eip_write_tag`、`ethercat_write_sdo`、
  `ethercat_set_state`、`profinet_dcp_set`、`bacnet_write_property`）全部
  `risk=HIGH`、默认 `dry_run=True`、捕获改前值供 undo。
- **审批**：真实写入需具名审批人 —— CLI `iaiops approve` 双重确认后才放行。
- **未经授权绝不写生产控制系统**；AI 结论仅 advisory，引用真实信号出处，宁可
  `insufficient_evidence` 不臆测。
- 各协议的验证状态（✅ 已自测 / 待核实）见 edition skill 的支持版本矩阵，
  标 `待核实` 的不得当既成事实。

## Setup（各 edition 相同）

`iaiops init` 交互写 `~/.iaiops/config.yaml`；凭据进加密存储
（`~/.iaiops/secrets.enc`，主密码 `IAIOPS_MASTER_PASSWORD`）。`iaiops doctor`
逐端点探活。协议参数、模拟器自测、MCP JSON 示例见 README 与各 edition skill。
