<!-- mcp-name: io.github.industrial-aiops/iaiops -->

# Industrial-AIOps（工业 AIOps）

[English](README.md) · **中文**

**面向 AI 智能体的「受治理、厂商中立」工业数据 tap + 智能排查 —— 本包 14 种现场协议（加能源版全线 17 种）、读优先工具：** OPC-UA（含历史访问 HDA + tag 自动发现）、Modbus-TCP/RTU（字节序自动探测 + 厂商寄存器模板）、S7comm、三菱 MC、**欧姆龙 FINS**（纯标准库客户端）、MTConnect、MQTT/Sparkplug B（完整解码）、EtherNet/IP（罗克韦尔/AB Logix）、EtherCAT（pysoem/SOEM）、PROFINET（DCP）、SECS/GEM（HSMS 半导体/面板设备）、HART-IP（过程仪表）、BACnet/IP（楼宇）、**IO-Link**（主站 JSON 集成），另加两层厂商 REST **只读**面——**BAS 监控器层**（Johnson Controls Metasys / Tridium Niagara，位于 BACnet 现场连接器之上，building 版）与 **Ignition Gateway MES/SCADA 只读层**（Inductive Automation Ignition 的 HTTP/Gateway Web API——模块健康、tag 浏览/读取、报警、tag 历史，factory 版）—— 外加 AI 停机根因 copilot（含 `downtime_triage` 编排器）、**保守基线学习**、**ISA-18.2 报警洪泛分析**、**历史库读回**（RCA 事故前证据）、**老 PLC 程序讲解**（ST/AWL/L5X）、**九个按行业版**（fab / factory / process / building / water / warehouse / clinical / renewables / plcnext，各自携带只读、仅建议的行业检查:SPC、PID 回路、经济器、产能瓶颈、医用气体、消毒 CT …）、**开放格式导出**（`iaiops export` CSV/SQLite/Parquet）+ **Prometheus/Grafana 桥**、数据质量看门狗、UNS 治理、OEE/停机分析、资产盘点，以及**信创**（TDengine/IoTDB 时序库下沉 + 防护指南/等保2.0/IEC 62443 合规对照、合规报告 + 证据包）。**能源版（变电/电力：IEC-104 / DNP3 / IEC-61850）为独立包 [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)。**

Industrial-AIOps 是 [industrial-aiops](https://github.com/industrial-aiops) 组织下的 OT/工控线产品。它是一个**工厂级、厂商中立、受治理的数据 tap**：让 AI 智能体跨多种现场协议**安全地"读"**工业控制系统;再叠加一个**跨协议智能层**——定位"没数据"的断点、分析报警洪泛（ISA-18.2）、给数据可信度打分、排查不健康 tag、算 OEE / 分类停机、建主动资产台账、把 OPC-UA 地址空间自动发现成语义资产模型,以及旗舰能力 **AI 停机根因 copilot**(把证据关联成**带证据引用、仅建议**的结论)。

设计上**读优先**;少数写/命令路径属 OT 高危,受 **MOC(变更管理)纪律**门控。所有工具都经过一套内置治理 harness(审计 / 预算 / 风险分级 / 回滚)。

> **v0.14.0 — 验证状态(诚实标注)。** 纯分析 + OPC-UA 路径用**真实 in-process asyncua 服务器**测;信创绑定用**真库 + 容器**跑过:**IoTDB** + **TDengine**(真容器写→读 round-trip)**已验证**;HART 命令编解码层对 `hart-protocol` 已验证。**菲尼克斯 PLCnext vPLC** 经其 OPC-UA server(in-process asyncua 复现 `Arp.Plc.Eclr` 地址空间)+ Modbus-TCP 过程数据块 **route-verified**(`tests/test_plcnext_route.py`),真机 `待核实`。**Modbus-RTU(真串口)已验证**(2026-07-02):`socat` PTY 对 + `pymodbus` RTU 服务器搭真串口链路,读操作经真实 RTU 帧 round-trip(`tests/test_modbus_rtu_live.py`);尚未对具体物理 RS-485 设备验证。**BACnet/IP 读路径已验证**(2026-07-02):Linux 容器内对**真实 bacpypes3 虚拟 BACnet/IP 设备**,经真实异步 BAC0(2024+)协议栈完成 Who-Is + present-value 真 round-trip(`tests/test_bacnet_live.py`)。新增 **欧姆龙 FINS** 对 in-repo mock FINS UDP/TCP 响应器验证(`tests/test_fins.py`);新增 **IO-Link** 对 in-process mock 主站双方言验证(`tests/test_iolink.py`)。两层新增厂商 REST 只读面均 **mock 验证**:**BAS 控制器层**对 in-repo mock 监控器双方言(Metasys OpenBlue REST + Niagara oBIX/REST)、**Ignition Gateway** 读层对 in-repo mock Gateway 双 flavor(`webdev` / `gateway`)验证;真实 Metasys/Niagara 控制器(含原生 oBIX-XML 编码)与真实 Ignition 网关(确切 API 版本/路径)仍 `待核实`。**仍 `待核实`(预览、未经硬件验证):** 欧姆龙真机(含 EM bank)、IO-Link 真机 datapoint 路径、BACnet 写/COV/趋势(真 HVAC)、HART-IP 线传输(真网关)、EtherCAT(无软件仿真器——仅 Linux + root + 真总线)、物理 Modbus-RTU RS-485 设备、真机 PLCnext。S7/MC/EtherNet-IP/SECS-GEM 用 mock 客户端;MTConnect 用静态 XML;Sparkplug 用合成 protobuf。(能源版 IEC-104 / DNP3 / IEC-61850 的验证状态见 [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) 仓库。)详见**安全与治理**。

---

## 为什么是它

OT 现场正是最该给智能体"上紧箍咒"的地方:**先读、绝不盲写**。Industrial-AIOps 就是那个**安全、中立的"读"楔子**——一个包、一个 MCP server、多种协议——配上治理与智能层,把原始读数变成可执行的诊断。

与 IT 线的关键差异:OT 走 **monorepo**(共享 core + 每协议一个 connector + 按行业打包的 edition),交付时按现场只装那 1–2 种协议。

## 🧪 测试与共创 / Beta testing & co-creation

**我们在找现场测试伙伴。** 软件里能验证的我们都验证了(真实 in-process 服务器、真实协议库、Docker 容器 loopback)——剩下的 `待核实` 清单只有真设备能回答:物理 Modbus-RTU(RS-485)、EtherCAT 从站、HART 网关、在线 BACnet 楼宇设备、在线 Metasys/Niagara BAS 控制器、在线 Ignition 网关、国产 PLC(汇川/信捷)、真机 PLCnext、真实变电站 RTU/IED、欧姆龙 FINS 真机、IO-Link 主站。如果你是 OT 工程师、系统集成商或工厂团队,手上有任何这类设备:装上 `iaiops`,对你的设备跑一遍 `iaiops doctor`,把结果告诉我们。**经你验证的设备会署名写进支持矩阵**;现场反馈的问题我们优先分诊;功能可以通过 GitHub Issues/Discussions 直接共创。

**We're looking for field-testing partners.** Everything software-verifiable has been verified; what's left on the honest `待核实` list only real equipment can answer. Run `iaiops doctor` against your gear and tell us what happened — **verified-equipment reports get credited in the support matrix**, field-reported issues get fast triage, and features are co-designed in the open.

👉 **参与入口 | Start here: [#28 — 招募现场测试伙伴 | Call for field-testing partners (v0.10.0)](https://github.com/industrial-aiops/industrial-aiops/issues/28)**(置顶 issue)

### 边缘部署与生态定位(edge-native / Margo)
iaiops 以**边缘应用(edge application)**的形态跑在加固、集中管理的**边缘主机**上——不抢主机、也不抢编排层。它天然对齐 [Margo](https://margo.org/) 工业边缘互操作标准的角色划分:*主机/设备* = 不可变边缘 OS,*合规编排器* 按期望状态下发工作负载,而 **iaiops = OT 域应用**(只读 tap + 跨协议 RCA,以受治理的 MCP 工具暴露),并可对接**本机 LLM 脑**做完全离线(气隙)诊断,数据不出厂。
> **诚实状态:** iaiops 是天然的 Margo 边缘应用,但**目前尚未 Margo-compliant**——容器镜像 + application description + 公开的 conformance 结果均为 roadmap `⏳`(见 **[docs/MARGO-ALIGNMENT.md](docs/MARGO-ALIGNMENT.md)** 与 `docs/ROADMAP.md`)。在那份测试结果出来前,任何材料都不声称 *Margo-compliant*。

容器 + application-description **骨架**见 **[`deploy/margo/`](deploy/margo/)**(加固 Dockerfile · compose · 标 `待核实` 的 app 描述符);复用该镜像的按主机分发覆盖层存放于 **[`deploy/`](deploy/)**(每个候选边缘主机一个目录)。

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

**协议 extras:** `opcua` · `modbus` · `s7` · `mc` · `fins`(纯标准库,不 pin 任何依赖)· `eip` · `mtconnect` · `sparkplug` · `secsgem` · `ethercat` · `profinet` · `bacnet` · `hart` · `iolink` · `bas`(BAS 监控器层 REST,复用 mtconnect HTTP pin)· `ignition`(Ignition Gateway 只读层,复用 mtconnect HTTP pin)· 另有 `tdengine` · `iotdb` · `influxdb`(时序库下沉)· `nats`(流出口)· `ollama`(本机 LLM 叙述)· `export`(Parquet 导出)· `all`(全部可 pip 装的 connector)。

**Edition 捆绑**(与同名 `IAIOPS_MCP` profile 对应——按行业只装该垂直跑的协议):
`fab`(secsgem+opcua+s7+modbus)· `factory`(离散制造全套:opcua+modbus+s7+mc+fins+eip+mtconnect+sparkplug+ethercat+profinet+iolink+ignition)· `process`(opcua+modbus+hart)· `building`(bacnet+modbus+opcua+iolink+bas)· `water`(水处理:modbus+opcua+hart)· `warehouse`(仓储/物料搬运:eip+profinet+modbus+opcua+sparkplug)· `clinical`(医疗设施:bacnet+modbus+opcua)· `renewables`(光伏/风电:modbus+opcua+sparkplug)· `plcnext`(opcua+modbus)。能源捆绑在 [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) 包内。

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
  - name: omron1
    protocol: fins                   # 欧姆龙 FINS(默认 UDP;transport: tcp 走 FINS/TCP)
    host: 10.0.0.11
    port: 9600
  - name: iolm1
    protocol: iolink                 # IO-Link 主站 JSON 集成(只读)
    host: 10.0.0.21
    flavor: iotcore                  # ifm IoT-Core(默认)| rest(Balluff/Turck 风格)
  - name: uns
    protocol: mqtt
    host: broker.lan
    use_tls: true                    # → 8883
    topic: spBv1.0/#
```

### 对着仿真器测(每协议)

- **OPC-UA** —— `asyncua` demo server(测试套件就跑了一个真实 in-process 的)。
- **Modbus** —— ModbusPal 或 `pymodbus` server 仿真(RTU 可用 `socat` PTY 对搭软件串口)。
- **欧姆龙 FINS** —— in-repo mock FINS UDP/TCP 响应器(`tests/test_fins.py`)或备用 CP/CJ PLC。
- **IO-Link** —— in-process mock 主站(`tests/test_iolink.py`,双 JSON 方言)或台架上的 ifm/Balluff/Turck 主站。
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
iaiops fins words 100 --area DM -e omron1 --count 8   # 欧姆龙 FINS 内存区读
iaiops iolink scan -e iolm1                           # IO-Link 主站 + 连接设备扫描
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
IAIOPS_MCP=opcua,modbus iaiops-mcp          # 按协议/profile 选择性暴露(菜单式, stdio)
IAIOPS_MCP=menu iaiops-mcp                  # 打印菜单(各 selection 工具数)后退出
iaiops-mcp-opcua                            # 等价的命名入口(每协议一个)
iaiops-mcp-fab                              # 按 edition profile(fab/factory/building/…)
iaiops-mcp-brain                            # 只暴露跨协议脑(零协议)
IAIOPS_MCP=all iaiops-mcp                   # 显式全量(>100 工具会警告洪泛)
```

**0.10.0 起无默认值**:裸 `iaiops-mcp`(不设 `IAIOPS_MCP`)打印菜单到 stderr 并 exit 2,
不再静默暴露 100+ 工具。多进程站点(1 脑 + N 协议):跑一个 `iaiops-mcp-brain`,协议
server 各自加 `IAIOPS_MCP_NO_BRAIN=1` 去掉脑避免重名(`protocols_supported` 仍保留)。
MCP 客户端按产线给每个 server 配一个 `IAIOPS_MCP` 菜单 = 现场只暴露该站点的 1–2 个协议 + 默认随附的"脑"工具。

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

### 6. 行业版(楼宇 / 水处理 / 仓储 / 医疗 / 光伏风电 / PLCnext / 能源)

楼宇(`IAIOPS_MCP=building`):BACnet/IP 设备发现 / 对象列表 / 读属性 / 读点位(HVAC/厂务)+ 有界 COV 订阅 + TrendLog 读取;`bacnet_write_property` 为 MOC 门控高危写。水处理(`IAIOPS_MCP=water`):modbus+opcua+hart + 水行业 tag 语义(溶解氧/ORP/余氯/氨氮/TSS/跨膜压差/加药/曝气)+ 水行业 Modbus 模板。能源(变电/电力)在独立包 [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy):IEC-104 / DNP3 / IEC-61850 MMS 只读监测。

**0.11/0.12 新增行业版**(每版都带自己的只读、引用优先、仅建议的检查工具,只在选中该 edition 时加载):
- **仓储/物料搬运**(`IAIOPS_MCP=warehouse`,eip+profinet+modbus+opcua+sparkplug):输送/分拣驱动 + VFD/电表 + WMS/WCS 网关 + AMR 遥测;版工具 `line_bottleneck`(约束理论产能瓶颈)+ `sortation_health`;复用 PdM / `downtime_triage` / OEE。
- **医疗设施**(`IAIOPS_MCP=clinical`,bacnet+modbus+opcua):把医院设施作为区别于普通楼宇的患者安全垂直;版工具 `isolation_room_check`(负压/正压隔离病房压差)、`medical_gas_check`(医用气体报警屏)、`or_environment_check`(手术室温湿度/压力包络)。
- **光伏/风电**(`IAIOPS_MCP=renewables`,modbus+opcua+sparkplug):PV 逆变器(SUN2000/Growatt 模板)+ 风机控制器 + 场站 SCADA + Sparkplug 遥测;版工具 `pv_performance`(组串性能对比)。
- **PLCnext 打包版**(`IAIOPS_MCP=plcnext`,opcua+modbus):菲尼克斯 PLCnext 虚拟化 PLC,经其内置 OPC-UA server(`opc.tcp` 4840)+ Modbus-TCP 过程数据 server,不新增 connector;route-verified,真机 `待核实`。

### 7. 保守基线学习(0.10 新增)

`baseline_learn/check/status`(CLI `iaiops baseline …`)——**变更日志式基线,明确不是黑盒异常检测**:鲁棒 p1/p99 + 中位数/MAD 带;样本太薄(<100 条或 <24h)**拒绝学习**并明说缺什么;操作员变更记录后从变更点重新学习;默认静默——只有超带 >3×MAD **且**连续 ≥3 个样本才报,每次违规都引用基线窗口和越界样本。

### 8. 历史库读回 + RCA 事故前证据(0.10 新增)

`historian_query` / `historian_coverage`(CLI `iaiops historian query|coverage`)把写进 sqlite/TDengine/IoTDB 的历史查回来;配置 `historian:` 块后,RCA copilot 自动拉取**事故前 2 小时窗口**作为一类新证据(引用注明来源/窗口/样本数)。不配则输出逐字节不变(有测试证明)。

### 9. 老 PLC 程序讲解(0.10 新增)

`plc_program_outline/xref/section`(CLI `iaiops program …`)对**导出的**程序文件(西门子 SCL/ST、AWL/STL、罗克韦尔 Studio 5000 `.L5X`)做结构化提取——块/变量/调用图/定时器/交叉引用,每个元素带 `source_file` + 行号(L5X 带梯级号),讲解 agent 必须引用真实位置。绝不上传/连接在线 PLC;XXE 加固。

### 9b. 停机分诊 + 老 PLC 可维护性 + Agent 技能(0.11/0.12 新增)

- **停机分诊 copilot**(`downtime_triage`):把**报警级联 + RCA 结论 + PdM 前兆**编排成一次分诊,并核对首出报警是否与诊断出的根因一致;仅建议、引用优先(基于早期的 `alarm_cascade` 首出重建与 `pdm_forecast` 到阈时间预警)。
- **老 PLC 可维护性**(`plc_program_visibility`):对**导出的** ST/AWL/L5X 程序做风险/可维护性读评(体量、块数、交叉引用密度、无注释段),绝不上传在线 PLC;与 `plc_program_outline/xref/section` 讲解器配套。
- **每版工具机制**(`mcp_server/profiles.py` 的 `EDITION_MODULES`):某个 edition 可携带自己的 `@mcp.tool` 组,**仅在选中该 edition 时加载**——裸协议键与常驻脑都不加载,故各版专用工具不污染其他面、不膨胀基座。各版签名工具:仓储 `line_bottleneck`/`sortation_health`;医疗 `isolation_room_check`/`medical_gas_check`/`or_environment_check`;楼宇 `economizer_check`/`zone_comfort`;过程 `control_loop_health`/`heat_exchanger_fouling`;半导体 `spc_check`/`defect_pareto`;工厂 `changeover_analysis`;水处理 `disinfection_ct`/`water_quality_compliance`;光伏风电 `pv_performance`。
- **Agent 技能**:仓库随附一个路由技能(`skills/iaiops`)+ **九个**按行业技能(`iaiops-fab` / `iaiops-factory` / `iaiops-process` / `iaiops-building` / `iaiops-water` / `iaiops-warehouse` / `iaiops-clinical` / `iaiops-renewables` / `iaiops-plcnext`),把 agent 路由到正确的 MCP server 并说明工具面。

### 10. ISA-18.2 报警洪泛分析 + 合规报告(0.9 新增)

`alarm_flood_analysis`(洪泛片段/抖动报警/常驻报警/合理化 worksheet,CLI `iaiops diag alarm-flood|alarm-worksheet`);`iaiops compliance report`(等保 2.0 二/三级状态 + IEC 62443 FR1–6 对照 + 诚实差距清单,md/html)与 `iaiops compliance evidence`(审计证据 zip,哈希链校验)。辅助整改,非认证。

### 11. 数据导出 + Prometheus/Grafana 桥(0.9 新增)

`iaiops export csv|sqlite|parquet` 从本地 SQLite 存储按时间/端点/tag 过滤导出(Parquet 需 `iaiops[export]`);`iaiops metrics serve --port 9184` 暴露 Prometheus `/metrics`(默认只绑 127.0.0.1),Grafana 配方见 `docs/GRAFANA.md`。

### 12. 信创 / 国产时序库下沉

`historian_push` 把任意 connector 归一化后的数据写入本地 SQLite 或国产时序库 **TDengine** / **IoTDB**(不自建库、不绑 InfluxDB)。`compliance_mapping` 对照《工控系统网络安全防护指南》给诚实的逐项状态;`compliance_frameworks` / `compliance_dengbao_levels` 给等保 2.0 + IEC 62443 对照与二/三级增量。

---

## 安全与治理

- **读优先**:**166 个受治理工具里 156 只读**(每版工具只在选中对应 edition 时加载,故裸协议/单 edition 面比该全线总数小);读侧新增两层厂商 REST **只读**面——BAS 控制器层(Metasys/Niagara,building 版)与 Ignition Gateway MES/SCADA 层(factory 版);10 个写/命令工具(`s7_write_db`、`mc_write_words`、`fins_write_words`、`mqtt_publish`、`eip_write_tag`、`ethercat_write_sdo`、`ethercat_set_state`、`profinet_dcp_set`、`bacnet_write_property`、`bas_command`)全部 `[WRITE][risk=HIGH][MOC]`(`bas_command` 默认关闭 + 生命安全对象 denylist)。
- **破坏性操作**:dry-run 默认 + 双重确认 + MOC 门控 + 需记录审批人(一次性 `iaiops approve` 令牌;未配置 `risk_tiers` 时 high/critical 默认 `dual` 层);10 个写工具中 9 个**捕获改前值/状态并登记 undo 描述符**,例外是 `mqtt_publish`(即发即弃的 MQTT/Sparkplug 命令没有自动逆操作)与 `ethercat_set_state`(状态切换没有干净的逆操作)——二者**无自动 undo**。
- **治理 harness**:每个工具都过策略预检(策略引擎 fail-closed)+ 预算/失控熔断 + 风险分级 + 审计落库 `~/.iaiops/audit.db`(SHA-256 哈希链防篡改 + `iaiops audit verify`;高危写在审计不可用时拒绝执行);任何注册工具缺治理标记,MCP server 拒绝启动。
- **机密**:Fernet 加密库,绝不明文;配置目录权限告警。
- **品牌隔离**:厂商中立,不跨品牌桥接。
- **质量门**(发版前全绿):pytest + ruff + bandit(0 Medium+);全 MCP 工具带治理标记。

---

## 发布渠道

- **PyPI**:`pip install iaiops`(能源版 `pip install iaiops-energy`)
- **GitHub**:https://github.com/industrial-aiops/industrial-aiops
- **MCP Registry**:`io.github.industrial-aiops/iaiops`
- **ClawHub**:`iaiops`
- **文档**:`docs/CHINA.md`(信创)· `docs/ROADMAP.md`(路线图)· `CHANGELOG.md`(总体/技术架构 HLD 为内部设计文档,不随本仓发布)

## 许可

MIT。提交/包/版权统一署名 **wei `<zhouwei008@gmail.com>`**。
