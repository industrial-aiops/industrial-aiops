<!-- mcp-name: io.github.industrial-aiops/iaiops -->

# Industrial-AIOps（工业 AIOps）

[English](README.md) · **中文**

**面向 AI 智能体的「受治理、厂商中立」工业数据 tap + 智能排查 —— 12 种现场协议、读优先工具：** OPC-UA（含历史访问 HDA + tag 自动发现）、Modbus-TCP/RTU（字节序自动探测 + 厂商寄存器模板）、S7comm、三菱 MC、MTConnect、MQTT/Sparkplug B（完整解码）、EtherNet/IP（罗克韦尔/AB Logix）、EtherCAT（pysoem/SOEM）、PROFINET（DCP 发现）、SECS/GEM（HSMS 半导体/面板设备）、HART-IP（过程仪表）、楼宇版（BACnet/IP）、菲尼克斯 PLCnext vPLC —— 外加 AI 停机根因 copilot、数据质量看门狗、UNS 治理、OEE/停机分析、资产盘点，以及**信创**（TDengine/IoTDB 时序库下沉 + 防护指南/等保2.0/IEC 62443 合规对照）。**能源版（变电/电力：IEC-104 / DNP3 / IEC-61850）已拆为独立包 [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)。**

Industrial-AIOps 是 [industrial-aiops](https://github.com/industrial-aiops) 组织下的 OT/工控线产品。它是一个**工厂级、厂商中立、受治理的数据 tap**：让 AI 智能体跨多种现场协议**安全地"读"**工业控制系统;再叠加一个**跨协议智能层**——定位"没数据"的断点、分析报警洪泛（ISA-18.2）、给数据可信度打分、排查不健康 tag、算 OEE / 分类停机、建主动资产台账、把 OPC-UA 地址空间自动发现成语义资产模型,以及旗舰能力 **AI 停机根因 copilot**(把证据关联成**带证据引用、仅建议**的结论)。

设计上**读优先**;少数写/命令路径属 OT 高危,受 **MOC(变更管理)纪律**门控。所有工具都经过一套内置治理 harness(审计 / 预算 / 风险分级 / 回滚)。

> **v0.7.0 — 验证状态(诚实标注)。** 纯分析 + OPC-UA 路径用**真实 in-process asyncua 服务器**测;能源/信创绑定在 2026-06-30 的验证轮里用**真库 + 容器**跑过:**IEC-104**(真 c104 loopback)、**IoTDB** + **TDengine**(真容器写→读 round-trip)**已验证**;HART 命令编解码层对 `hart-protocol` 已验证。**Modbus-RTU(真串口)现已验证**(2026-07-02):用 `socat` PTY 对(软件级 null-modem)+ `pymodbus` RTU 服务器搭真串口链路,连接器的 holding/input/coil/discrete 读操作经真实 RTU 帧 round-trip(`tests/test_modbus_rtu_live.py`);尚未对具体物理 RS-485 设备验证。**仍 `待核实`(预览、未经硬件验证):** DNP3、IEC-61850(真 IED)、BACnet(真 HVAC)、HART-IP 线传输(真网关)、EtherCAT(无软件仿真器——仅 Linux + root + 真总线)。S7/MC/EtherNet-IP/SECS-GEM 用 mock 客户端;MTConnect 用静态 XML;Sparkplug 用合成 protobuf。详见**安全与治理**。

---

## 为什么是它

OT 现场正是最该给智能体"上紧箍咒"的地方:**先读、绝不盲写**。Industrial-AIOps 就是那个**安全、中立的"读"楔子**——一个包、一个 MCP server、多种协议——配上治理与智能层,把原始读数变成可执行的诊断。

与 IT 线的关键差异:OT 走 **monorepo**(共享 core + 每协议一个 connector + 按行业打包的 edition),交付时按现场只装那 1–2 种协议。

---

## 安装

协议客户端库都是**可选 extras** —— 只装现场真正在跑的那 1–2 种(每个协议库都懒加载;基础包不装任何 extra 也能安装和导入,调用未安装的协议会返回一个**教学式错误**指向正确的 extra):

```bash
pip install "iaiops[opcua,modbus]"     # 只装你需要的协议
# 或单协议:  pip install "iaiops[s7]"   ·   全装:  pip install "iaiops[all]"
# 或按行业 edition 捆绑:  pip install "iaiops[fab]"

iaiops init                 # 交互式:加端点、加密存口令
iaiops doctor               # 配置 + 每协议连通性探测(可指向仿真器)
iaiops protocols            # 能力地图
```

**协议 extras:** `opcua` · `modbus` · `s7` · `mc` · `eip` · `mtconnect` · `sparkplug` · `secsgem` · `ethercat` · `profinet` · `iec104` · `dnp3` · `iec61850` · `bacnet` · `hart` · `tdengine` · `iotdb` · `all`。

**Edition 捆绑**(与同名 `IAIOPS_MCP` profile 对应——按行业只装该垂直跑的协议):
`fab`(secsgem+opcua+s7+modbus）· `factory`(离散制造全套)· `process`(opcua+modbus+hart)· `energy`(IEC-104/DNP3/IEC-61850+modbus+opcua)· `building`(BACnet+modbus+opcua)· `xinchuang`(TDengine+IoTDB 时序库)。

> **信创/离线:** 纯 Python 核心 + 可选 extras 支持**离线/气隙安装**(本地 wheelhouse + `pip install --no-index`)。国产时序库下沉(TDengine/IoTDB)、合规对照见 `docs/CHINA.md`。

### 主口令

机密(每端点口令、MQTT 凭据)**绝不**明文落盘——存在 `~/.iaiops/secrets.enc`(Fernet + scrypt)。导出 `IAIOPS_MASTER_PASSWORD` 让 MCP server/CLI 非交互解锁:

```bash
export IAIOPS_MASTER_PASSWORD='…'
```

### 配置示例 `~/.iaiops/config.yaml`(每协议一块)

```yaml
endpoints:
  - name: line1
    protocol: opcua
    endpoint_url: opc.tcp://plc.lan:4840
    tags:
      - { ref: "ns=2;i=5", label: temp, warn_high: 70, alarm_high: 90 }
  - name: plc2
    protocol: modbus
    host: 10.0.0.5
    port: 502
    unit_id: 1
  - name: meter1
    protocol: modbus                 # Modbus-RTU(串口):设 transport 或 serial_port
    transport: rtu
    serial_port: /dev/ttyUSB0
    baudrate: 9600
  - name: xmtr1
    protocol: hart                   # HART-IP 过程仪表(只读)
    host: 10.0.0.20                  # HART-IP 服务器/网关,默认端口 5094
  - name: rtu1
    protocol: iec104                 # 能源版:变电站遥测
    host: 10.0.0.30
    common_address: 1
  - name: uns
    protocol: mqtt
    host: broker.lan
    use_tls: true                    # → 8883
    topic: spBv1.0/#
```

### 对着仿真器测(每协议)

- **OPC-UA** —— `asyncua` demo server(测试套件就跑了一个真实 in-process 的)。
- **Modbus** —— ModbusPal 或 `pymodbus` server 仿真。
- **IEC-104** —— `c104` 可同时跑 server+client(真实 loopback)。
- **TDengine / IoTDB** —— 官方 docker 镜像(真实容器写读)。
- **EtherCAT** —— **无仿真器**(硬实时、raw-Ethernet),仅 Linux+root+真总线(如 Beckhoff EK1100 + EL 端子)。

---

## 使用

### CLI(读)

```bash
iaiops opcua read "ns=2;i=5" -e line1
iaiops opcua discover -e line1                       # tag 自动发现 → 语义资产模型
iaiops modbus holding 0 -e plc2 --count 4 --decode float32
iaiops modbus detect-byte-order 0 -e plc2 --count 2  # 字节序自动探测
iaiops hart pv -e xmtr1                               # HART 主变量(过程仪表)
iaiops mtconnect oee -e vmc1
iaiops mqtt nodes -e uns --timeout-s 15
iaiops opcua history "ns=2;i=5" -e line1 --start 2026-06-28T08:00:00Z   # HDA 历史
iaiops opcua monitor "ns=2;i=5" -e line1 --duration-s 20 --deadband 0.5 # CoV 变化捕获
iaiops diag dataflow -e line1 --ref "ns=2;i=5" --freshness-s 30          # 断点定位
iaiops diag dataquality-fleet --input feeds.json                        # 数据质量舰队视图
```

### CLI(写 —— 默认 dry-run,`--apply` 二次确认)

```bash
iaiops s7 write-db 1 INT 0 42 -e press1            # dry-run 预览
iaiops s7 write-db 1 INT 0 42 -e press1 --apply    # 二次确认提示
```

写=HIGH 风险层:**dry-run 默认 + 双重确认 + MOC 门控 + undo 捕获改前状态**。

### MCP server

```bash
iaiops-mcp                                  # 暴露全部工具(stdio)
IAIOPS_MCP=opcua,modbus iaiops-mcp          # 按协议/profile 选择性暴露(菜单式)
iaiops-mcp-opcua                            # 等价的命名入口(每协议一个)
iaiops-mcp-energy                           # 按 edition profile(energy/building/fab/…)
```

MCP 客户端按产线给每个 server 配一个 `IAIOPS_MCP` 菜单 = 现场只暴露该站点的 1–2 个协议 + 始终在的"脑"工具。

---

## 典型场景

### 1. AI 停机根因 copilot(旗舰)

把你能给的证据(报警事件、tag 采样、`diagnose_dataflow` 结论、设备状态序列)围绕事故窗口关联,返回**带证据引用、仅建议**的结论。读优先:它只提议一个人审批、MOC 门控、可回滚的动作,**不执行任何东西**。设计上抗幻觉——只引用输入里真实存在的信号,按与故障起点的时间邻近度加权(因在果前),证据不足时降级为 `insufficient_evidence` 并给出 `recommended_next_data`,绝不瞎猜。

```bash
# 让它自己采证据:给端点 + 窗口 + 要看的 ref,它自己拉
iaiops diag rca-live -e line1 --start 2026-06-28T10:00:00Z \
  --asset line1 --ref "ns=2;i=5" --ref "ns=2;i=6"
```

### 2. OPC-UA tag 自动发现 + 语义建模

走地址空间,收集每个 Variable,带上数据类型/值/工程单位,**启发式语义分类**(温度/压力/流量/设定值/报警/状态…),按 browse path 分组成资产,给每个 tag 提一个干净的规范别名,并出一份命名质量报告(别名冲突/晦涩名)。**只读/仅建议**——绝不在服务器上改名(那是 OT 高危)。默认跳过 ns=0 基建。

```bash
iaiops opcua discover -e line1
```

### 3. 数据质量看门狗

给每个 tag 在"数据可不可信"维度打 0–100 分:陈旧、死心跳、坏质量、flatline(卡值)、采样缺口、统计异常——按端点和舰队汇总,排出最差 offender。可配每 tag/每 feed 的陈旧阈值;心跳/flatline 是一等公民。`data_quality_fleet_rollup` 给跨端点的舰队视图。

### 4. Modbus 字节序自动探测 + 厂商模板

把一块原始寄存器按所有候选字节序(AB/BA、ABCD/DCBA/BADC/CDAB)解一遍,按提示值/合理区间打分选出正确字节序——**纯逻辑、无需设备**。配套一组厂商寄存器模板(Eastron SDM630、Schneider PM5xxx 等)把寄存器块解成命名工程量。

### 5. HART-IP 过程仪表(只读)

经 HART-IP 服务器/网关读现场仪表的通用变量:设备身份、主变量、动态变量 + 回路电流。**不暴露**写/设备专用命令(对在线仪表是 OT 高危)。命令编解码层对 `hart-protocol` 已验证;HART-IP 线传输 `待核实`。

### 6. 能源版 / 楼宇版

能源:IEC-104(变电站遥测)、DNP3、IEC-61850 MMS,只读监测。楼宇:BACnet/IP 设备发现 / 对象列表 / 读属性 / 读点位(HVAC/厂务)。控制方向一律不暴露。

### 7. 信创 / 国产时序库下沉

`historian_push` 把任意 connector 归一化后的数据写入国产时序库 **TDengine** / **IoTDB**(不自建库、不绑 InfluxDB)。`compliance_mapping` 对照《工控系统网络安全防护指南》给诚实的逐项状态。

---

## 安全与治理

- **读优先**:绝大多数工具是 `[READ]`(risk=low);写/命令是 `[WRITE]`(risk=high)。
- **破坏性操作**:dry-run 默认 + 双重确认 + MOC 门控;undo 捕获改前状态。
- **治理 harness**:每个工具都过策略预检 + 预算/失控熔断 + 风险分级 + 审计落库 `~/.iaiops/audit.db`。
- **机密**:Fernet 加密库,绝不明文;配置目录权限告警。
- **品牌隔离**:厂商中立,不跨品牌桥接。
- **质量门**(发版前全绿):pytest + ruff + bandit(0 Medium+);全 MCP 工具带治理标记。

---

## 发布渠道

- **PyPI**:`pip install iaiops`(最新 0.7.0)
- **GitHub**:https://github.com/industrial-aiops/industrial-aiops
- **MCP Registry**:`io.github.industrial-aiops/iaiops`
- **ClawHub**:`iaiops`
- **文档**:`docs/HLD.md`(总体架构)· `docs/PLATFORM-ARCHITECTURE.md`(技术架构)· `docs/CHINA.md`(信创)· `docs/ROADMAP.md`(路线图)· `CHANGELOG.md`

## 许可

MIT。提交/包/版权统一署名 **wei `<zhouwei008@gmail.com>`**。
