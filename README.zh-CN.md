<!-- mcp-name: io.github.industrial-aiops/iaiops -->

# Industrial-AIOps（工业 AIOps）

[English](README.md) · **中文**

**让 AI 说清楚产线为什么停了 —— 而且每句结论都带证据引用。**

一个厂商中立、**读优先**的现场数据 tap。它讲 **14 种现场协议**，把跨协议的证据在时间上对齐，
交给智能体的是**带引用的裁决**，不是猜测。每次调用都留审计；读取路径绝不回连。

```bash
pip install "iaiops[opcua]"      # 按现场装，或 [all]
iaiops init                      # 生成 ~/.iaiops/config.yaml
iaiops doctor                    # 先自检，再谈信任
```

也可以直接跑容器 —— **cosign 签名**、**非 root**。它以 stdio 讲 MCP，所以要保持 stdin 打开，并挂一个卷存审计库：

```bash
cosign verify --key deploy/margo/cosign.pub ghcr.io/industrial-aiops/iaiops:0.26.0-factory
docker run -i --rm -v iaiops-state:/home/iaiops/.iaiops \
  ghcr.io/industrial-aiops/iaiops:0.26.0-factory
```

要加固部署或离线部署（只读根文件系统、`cap_drop: ALL`、no-new-privileges、可选端侧 LLM），
见 [`deploy/margo/compose.yaml`](deploy/margo/compose.yaml) 与 [`deploy/airgap/`](deploy/airgap/)。
分析引擎**不需要 GPU、不需要模型 API** —— 它是确定性算法；LLM 可选，且只负责把结论讲成人话。

## 它能干什么

|  |  |
|---|---|
| **读** | OPC-UA（含 HDA 历史访问、tag 自动发现）· Modbus TCP/RTU · S7comm · 三菱 MC · 欧姆龙 FINS · MTConnect · MQTT/Sparkplug B · EtherNet/IP · EtherCAT · PROFINET · SECS/GEM · HART-IP · BACnet/IP · IO-Link —— 另有两层只读 REST 面：BAS 监控器（Metasys / Niagara）与 Ignition Gateway |
| **查得清** | `scan` 现场勘察(零发包预览,给人签字的那份)· `readiness` 这个站点今天能跑什么、还差什么(零联网)· `collect` 有界评估采集 + 断点续跑 · `store` 留存与剪枝 |
| **想明白** | 停机根因 copilot（旗舰;四级结论 + 假设账本 + 时序排除）、**从采集历史实测的 OEE**(可用率/性能/质量 + 六大损失,可出自包含 HTML 报告)、报警洪泛分析（ISA-18.2）、数据流断点定位、数据可信度打分、资产台账、老 PLC 程序讲解（ST/AWL/L5X） |
| **查得完** | `investigate` 八步证据闭环 —— 定义事件 → 取证 → 归一校验 → 压缩排序 → 关联时间线 → 验假设 → 知识校验 → 结论闭环;每一步走不通时说清是**你**没给还是**产品**给不了 · `tags` 点表语义确认(导出表 / 静态页 / 产出 config 补丁) |
| **越用越准** | `case` 事故案例闭环 —— 标签从审计轨迹自动来,确认只需一次点选,学出本站自己的原因权重 |
| **管得住** | 审计 · 预算 · 风险分级 · 回滚 —— 每一次调用都过，MCP 与 CLI 两条前端走同一引擎 |
| **归你自己** | 无遥测、不回连。有六个工具按设计**可以**把数据发出去（`stream_publish`、`stream_publish_event`、`uns_publish`、`historian_push`、`mqtt_publish`、`rca_narrate`）—— `IAIOPS_NO_EGRESS=1` 会把这六个一并摘除，形成离线姿态 |

本包内含**十个行业版**：fab · factory · process · building · water · warehouse · clinical ·
pharma · renewables · plcnext，各自带只读的行业建议检查。变电/电力（IEC-104 · DNP3 · IEC-61850）为独立包
[`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy)。

## 头五分钟

四条命令。其中只有一条会碰设备，而且它在发出任何东西之前，先把要发的内容原样打印出来。

```bash
pip install "iaiops[modbus]"     # 选你真有的那个协议，或者 [all]
iaiops init                      # 交互式配一个端点
iaiops doctor                    # 配置、凭据、连通性 —— 以及版本号
iaiops readiness                 # ← 先跑这条。零联网。
```

`readiness` 只读你的配置和本地库，回答一个问题：**这个站点今天能跑哪些场景，每个缺口还差什么？**
每个缺口都附带能补上它的那条命令，并按"补上它能解锁多少"排序。不需要 agent、不需要云、
不需要账号，线上不发一个包。

然后是顺序不能颠倒的那三件事 —— 先看现场有什么，再取一份有界的样本，最后才谈说明：

| | | 碰设备吗 |
|---|---|---|
| **勘察** | `iaiops scan plan` → `iaiops scan run` | 预览零发包；run 会逐类列出它发过的每一个包 |
| **取数** | `iaiops collect run line1 --duration 7d` | 会 —— 而且会报告它看见了什么**以及漏掉了什么** |
| **声明** | `iaiops tags export` → 人填 `role` → `iaiops tags apply --by <你>` | **不会** —— `role` 列是故意留空的 |
| **说明** | `iaiops oee measure --since … --until …` · `iaiops investigate open` · `iaiops diag rca` | **不会** —— 全部基于已采集的历史 |

**想看完整流程对着真实设备跑一遍（约两分钟，含一次真实的中途断连）**，执行
`./demo/oee-line/run_demo.sh` —— 不需要硬件、不需要配置，也不会在临时目录外写任何东西。
[demo/oee-line/](demo/oee-line/) 说明了每一步是干什么的，以及那些数字能和不能说明什么。

## 为什么"读优先"

OT 正是最该给智能体上紧箍咒的地方。**读**路径才是产品本体；少数写路径属 OT 高危，默认关闭，
并受 MOC 纪律门控 —— dry-run、一次性审批令牌、undo 捕获、hash 链审计。

## 证明这套分析不需要模型

分析层够不着语言模型 —— 这是一条守卫，不是一句形容词：`tests/test_brain_is_llm_free.py`
扫描 **8 个包**（`brain` `discovery` `runtime` `readiness` `collect` `knowledge` `retain`
`connectors`）里任何能通向模型的 import，**扫出来是空的**才算通过。模型只出现在两个地方，
且都不承重：`rca_narrate` 把一个**已经算完、已经带引用**的结论换个说法，以及 agent 前端决定
调用**哪个**工具。两个都拿掉，数字还是那些数字。

但那条守卫是**静态**的 —— 它证明的是「不可能调用」。对做 CSV/验证的人来说，他要签的是**跑过**
的那一句，所以它现在真的会跑：

```bash
iaiops verify determinism --out determinism-record.json
```

一份**钉死在仓里**的数据集依次过可用率、产量计数、六大损失、ISA-18.2 告警负荷、控制图、
保守基线、RCA 副驾；每个结果规范化编码后取 SHA-256。整套**在本进程跑两遍，再在两个
`PYTHONHASHSEED` 不同的全新解释器里各跑一遍** —— 最后这一臂才抓得到集合/字典迭代顺序渗进结果，
单跑一次永远抓不到。全程 socket 抛异常，所以一个伸手去找设备或主机名的计算会**在这里失败**，
而不是在恰好联网的机器上安静地成功。跑完再问一句：这一趟**拉进来**了什么模型库？
**本来就加载着**的（MCP server 进程为了那个可选的叙述工具持有 `iaiops.core.llm`）只记录、不定罪 ——
只有这一趟自己 import 的才判它不合格。

记录分两半：`result`（每次都相同，签的是这一半）与 `context`（这次在什么时间、什么机器上跑的）。
**两次好的运行不会得到逐字节相同的记录文件**，而一定有人会去 diff 它们 —— 所以两半是分开命名的，
不是混在一起。

这才是这句话能用的形态：不是「我们的模型很准」（在 GMP 语境下不构成任何证据），
而是一条能写进 IQ/OQ 的测试用例 —— **移除模型、断网、重跑标准数据集、比对哈希** —— 执行、签字。
MCP 侧同一个检查叫 `verify_determinism`；`iaiops verify suite` 只列出它覆盖了什么，不执行。

## 到底验证到什么程度

一句话：**对真实协议库、容器、in-process 服务器验过；尚未对真实产线设备验过。**
我们给证据分级，而不是笼统说"测过"—— 真容器 round-trip 和合成 fixture 不是同一种证据。

| 级别 | 含义 | 状态 |
|---|---|---|
| 真库 / 容器 / in-process 服务器 | OPC-UA（含证书 `Sign`/`SignAndEncrypt` 矩阵 + A&C）、Modbus-RTU 走 `socat` PTY + `pymodbus` 真串口、BACnet/IP 经 `bacpypes3` 双 IP 子网、IoTDB / TDengine 真容器写→读、HART 编解码对 `hart-protocol`、PLCnext 经 `asyncua` route 验证 | ✅ |
| Mock 验证（协议逻辑跑通，但无真设备） | 欧姆龙 FINS、IO-Link、BAS（Metasys / Niagara）、Ignition Gateway、EtherNet/IP PCCC、MTConnect 长轮询、Sparkplug B、S7 / MC / SECS-GEM | ⚠️ |
| **真实设备** | 物理 RS-485、EtherCAT 从站、真 HART 网关、在线 HVAC / BAS / Ignition、真 PLC | **每个协议都是零** |

**逐协议证据（包括每个测试"没覆盖什么"）见
[docs/VERIFICATION-RECORD.md](docs/VERIFICATION-RECORD.md)**，一协议一行，注明支撑该结论的测试。
每一条 `待核实` 都是卡在硬件上，不是忘了 —— 每一条都点名了能了结它的那台设备。

## 🧪 测试与共创 / Beta testing & co-creation

**我们在找现场测试伙伴。** 软件里能验证的我们都验证了(真实 in-process 服务器、真实协议库、Docker 容器 loopback)——剩下的 `待核实` 清单只有真设备能回答:物理 Modbus-RTU(RS-485)、EtherCAT 从站、HART 网关、在线 BACnet 楼宇设备、在线 Metasys/Niagara BAS 控制器、在线 Ignition 网关、国产 PLC(汇川/信捷)、真机 PLCnext、真实变电站 RTU/IED、欧姆龙 FINS 真机、IO-Link 主站。如果你是 OT 工程师、系统集成商或工厂团队,手上有任何这类设备:装上 `iaiops`,对你的设备跑一遍 `iaiops doctor`,把结果告诉我们。**经你验证的设备会署名写进支持矩阵**;现场反馈的问题我们优先分诊;功能可以通过 GitHub Issues/Discussions 直接共创。

**We're looking for field-testing partners.** Everything software-verifiable has been verified; what's left on the honest `待核实` list only real equipment can answer. Run `iaiops doctor` against your gear and tell us what happened — **verified-equipment reports get credited in the support matrix**, field-reported issues get fast triage, and features are co-designed in the open.

👉 **参与入口：[开一个 issue](https://github.com/industrial-aiops/industrial-aiops/issues/new)，标题里带上协议名和设备型号；或者直接邮件 <zhouwei008@gmail.com>。** 两条都是真人在看，而且会以当前版本为准回复。

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
`fab`(secsgem+opcua+s7+modbus)· `factory`(离散制造全套:opcua+modbus+s7+mc+fins+eip+mtconnect+sparkplug+ethercat+profinet+iolink+ignition)· `process`(opcua+modbus+hart)· `building`(bacnet+modbus+opcua+iolink+bas)· `water`(水处理:modbus+opcua+hart)· `warehouse`(仓储/物料搬运:eip+profinet+modbus+opcua+sparkplug)· `clinical`(医疗设施:bacnet+modbus+opcua)· `pharma`(制药:bacnet+modbus+hart+opcua)· `renewables`(光伏/风电:modbus+opcua+sparkplug)· `plcnext`(opcua+modbus)。能源捆绑在 [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) 包内。

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

### 从「不知道网上有什么」到一个实测的 OEE

`scan` 回答**外面有什么**。下面这几条回答**能拿它做什么、数字是多少**。
每一条都是真命令,没有一条是路线图。

```bash
iaiops readiness                                    # 零联网
```

这套装置**今天**能跑哪些场景;跑不了的,逐条说出**缺的那个具体输入**,
并按「补上它能解锁多少」排序。它不碰任何设备,所以可以对着一个**你还没拿到探测授权**
的站点跑 —— 而那正是最需要这个答案的站点。它只报告缺口,**永不替你填**
(§9.4/D16:猜出来的产量计数器会给出一个看起来很像样的 OEE,那比报错危险)。

```bash
iaiops collect plan line1 --duration 7d --interval-ms 1000   # 零联网
iaiops collect run  line1 --duration 7d --interval-ms 1000
iaiops collect run  line1 --duration 7d --resume             # 合过盖子之后
iaiops store status                                          # 本地库里有什么
iaiops store prune --sealed-before 2026-08-01 --apply        # 没有封存水位就拒绝
```

**有界**评估采集 —— 上限 14 天,而且操作员**必须说出终点**。故意没有「一直跑」模式:
OT 网络上的常驻进程要走变更审批,笔记本跑一周不用(D21)。每次运行都记录它
**没看见**的那些窗口,所以盲区永远不会被悄悄读成停机。

要从中得到 OEE,得声明三个位号 —— 哪个值代表在跑、哪个寄存器计数、
以及(质量因子需要)哪个计好品:

```yaml
endpoints:
  - name: line1
    ideal_cycle_time_s: 0.1
    tags:
      - {ref: "0",  role: run_state,   running_when: [2]}   # 2 = 运行
      - {ref: "10", role: total_count}
      - {ref: "11", role: good_count}
```

`running_when` 是**声明的,不是推断的**。在大多数 PLC 暴露的
`0=停机 1=空闲 2=运行 3=故障` 状态字上,「非零即运行」会把四种状态里的三种算成生产。

```bash
iaiops oee measure line1 --reported 97               # 对照厂里自己在用的数字
iaiops oee measure line1 --since 2026-03-02T06:00:00Z --until 2026-03-09T06:00:00Z
iaiops oee measure line1 --report oee.html --lang zh --site "一号厂区"
```

**用 `--since` / `--until` 限定测量窗口,两个一起给。** 不给的话,测量的周期是本地库里
该端点的**全部历史** —— 只跑过一次评估时没问题,一旦跑了两次就是错的:三月那次和八月
那次之间的几个月空档会变成一段巨大的盲区,**两次都测不出来**。

窗口是**足额计费**的。窗口里从未被采样的部分 —— 第一个样本之前、最后一个样本之后 ——
和中间的空洞一样计入盲区。所以**把问题缩到刚好有数据的那几分钟,并不能把覆盖率做高**:
问一个你只看到两小时的班次,得到的是「覆盖率 25%,拒绝报数」,而不是「我们看到的部分 100%」。

可用率只在采集器**看得见**的时间上计算,盲区被**排除**而不是算成停机;
另有性能、质量和六大损失。每个因子**只在它的输入被声明时才报告** ——
一个说明白缺了什么的部分 OEE,胜过一个里面塞了猜测的完整 OEE。

`--report` 写出**一个自包含 HTML 文件** —— 不从任何地方加载字体、脚本、样式或图片,
打开时零网络请求,所以离网笔记本能开,当附件转发不会坏。它的**第一节**是
「这次测量看见了什么」(覆盖率、盲区、实际节拍),**排在数字之前**;
而且带着销售材料通常会省掉的那一行:**每个数字要求了什么、还差什么**。

```bash
iaiops case open line1 --min-stop-s 300              # 每次长停机开一个案子
iaiops case list                                     # 每个都带着「之后有人做了什么」
iaiops case causes                                   # 确认时可用的固定词表
iaiops case confirm <id> --cause material_starvation --by wei
iaiops case agreement                                # 同意率 >90% 是警告,不是分数
iaiops diag learn-weights --site default             # 学出本站的原因权重画像
iaiops diag rca --input bundle.json --from-case <id> # 人的答案进入判决
```

标签是**已经在做的工作的副产品**:审计轨迹本来就记下了「谁在停机四分钟后动了什么」,
案子直接把它显示出来。确认是从固定词表里**选一个**,永远不是自由文本;
「不是事故」也是一个标签。而一个答案算不算**独立**,是**推导**出来的
(看它是不是我们自己排过的),答话的人无法自称。

### 调查本身 —— 八步,以及每一步需要什么

`readiness` 回答**这个站点能跑哪些场景**。这一条回答再往下一层的问题:
**如果明天出事了,我们实际能查到第几步?**

```bash
iaiops investigate plan                              # 什么都不联
```

八步证据闭环 —— 定义事件、收集证据、归一与校验、压缩排序、关联时间线、
验证假设、对照已知机理、结论与闭环。对每一步走不通的,它说清那是**你**还没提供的
(并给出该跑哪条命令),还是**这个产品**根本没法表达的。这两者把人送去完全不同的地方。

```bash
iaiops investigate open line1 --start <iso> --end <iso> --asset "一号线"
iaiops investigate show <id>                         # 它被留在什么状态
iaiops investigate list
```

同样的八步,跑在一个**真实的过去窗口**上,并持久化下来,可以回读和继续推进。
不联任何设备 —— 窗口已经过去了,它的证据就是当时采到的那些。

三条命令都能出可转发的那一份 —— 一个自包含 HTML 文件,离网笔记本能开:

```bash
iaiops investigate plan --report readiness.html --lang zh
iaiops investigate open line1 --start <iso> --end <iso> --report incident.html
```

和 `oee measure --report` **反着来,而且是故意的**:那条会**拒绝**为一次被拒的测量写文件,
因为 OEE 报告的内容是一个数字,文件存在本身就是「测过了」的断言。这一份的内容是
**走到哪、每一步还差什么** —— 所以卡住的那种情况**才是最值得转发的**,
对一个还没上仪表的站点,这就是全部交付物。它唯一不做的,是让一次卡住的调查看起来像做完了:
头条永远是那个走位(`2 / 8`),不是结论。

其中两步需要人先说出一件事:

```bash
iaiops relations declare press oven --by wei         # 谁喂谁
iaiops relations downstream press                    # 最近的在前
```

根因分析的**第二根轴**。只有时间的话,一次上游停机会产出一串同样自信的下游假原因 ——
在产线上,下游的同时发生**不管什么原因都是必然的**。正因为这个必然,它只能是声明,
不能是推断(D25)。没有它时间线照样跑,只是退化成单个设备 —— **并且它会说出来**。

```bash
iaiops knowledge mount pump-library.yaml --by wei    # ISO 14224 三层分离
iaiops knowledge check sensor_fault --protocol modbus
```

三个答案,而且前两个的区别就是全部要点:**一无所知**(库里没听说过这个原因 ——
这和「它没问题」完全是两回事)、**知道**、**知道且可排除**(这个原因的每一条机理
在这台设备上都不适用)。第三个是排序器做不到的强动作。它**永不确认** ——
把一个原因升到「已确认」只能来自排序之外:一次测量、一次复现,或一个人(D29)。

### 确认点表的含义

这个产品唯一拒绝推断的东西。在此之前,提供它的唯一办法是手改配置文件里的 `role:` ——
正是一百行就撑不住的那个办法。

```bash
iaiops tags export sheet.csv          # 每个被监控的位号一行;role 列是空的
# 人填 role + running_when
iaiops tags apply sheet.csv --by wei  # 打印出要贴进 config.yaml 的那几行
```

`role` 列导出时是**空的,哪怕紧挨着一个叫 `GoodPartsCounter` 的位号**。
名字不是声明;有的是工厂的 `GoodPartsCounter` 数的是别的东西,而选错产量计数器
会得出一个看着合理的 OEE —— 比报错更糟(D16)。

`apply` **产出补丁而不是替你写**。config.yaml 仍是唯一的真相源:`oee measure` 是直接
从配置里的位号对象读 `role` 的,所以另建一个存储会让 `readiness` 说「已满足」而
`oee measure` 仍然跑不了。`run_state` 没有 `running_when` 会被拒绝,理由和 `MonitorTag`
拒绝它一样 —— 「非零即运行」会把空闲和故障算成生产。

也可以在页面上逐行勾,而不是开表格软件:

```bash
iaiops tags page confirm.html --lang zh
```

HLD §13.9 的 App 前端,交付成**一个文件而不是一个服务**。在工控盒子里起 localhost 服务,
要回答绑哪个地址、谁认证;而这里每一处声明都强制 `--by`,**一个没有身份的页面
回答不了「是谁勾的」** —— 而那正是这一步存在的意义。所以页面只负责收集,作者在 `apply` 时给。

页面**不重新实现任何一条拒绝**。`run_state` 要 `running_when`、ref 必须被监控、
一个角色不能被两个位号认领 —— 用 JavaScript 抄一遍就是让它们和真正把关配置的那些漂移开,
而「页面说没问题、`apply` 拒绝」比没有页面更糟。它带脚本(它是个表单),但**不发任何网络请求**:
拔了网线照样用。

**这里故意没有 MCP 工具。** 让 agent 去填 role 列,正是 D16 存在就是为了禁止的那个猜测。

### CLI(读)

```bash
iaiops opcua read "ns=2;i=5" -e line1
iaiops opcua discover -e line1                       # tag 自动发现 → 语义资产模型
iaiops modbus holding 0 -e plc2 --count 4 --decode float32
# 字节序自动探测目前只有 MCP 工具 `modbus_detect_byte_order`,没有 CLI 命令
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

## 程序变更基线 —— 认可的那版逻辑动过没有

控制程序是一份受控文件，而现场发现「有人改过且没记录」的常规方式是**有人记得**。
把你认可的那一版记下来，之后问某一次导出动没动：

```bash
iaiops program snapshot ~/exports/Line3.scl --name Line3 --label "approved v3.2 / MOC-118"
iaiops program drift    ~/exports/Line3_today.scl --name Line3
```

快照存的是文件 SHA-256 加上每个 block 的结构指纹（名字/类型/语言、声明的变量、调用、分支条件、
定时器），**刻意不含行号、注释和 block 顺序** —— 否则在文件顶上加一行注释就会把整份程序报成变更，
这种工具一周内就会被关掉。落到磁盘上的是 block 名 + 哈希 + 计数，**不落任何声明、源码行或注释**，
所以这个库不是你程序的第二份拷贝。

三个判词，每个词都咬得很紧：

| 判词 | 含义 |
|---|---|
| `identical` | SHA-256 相同。**只有**这一种情况配得上这个词。 |
| `logic_changed` | 抽取到的结构变了 —— 逐 block 报，并指出 `variables` / `calls` / `branches` / `timers_counters` 里哪一类动了。 |
| `changed_outside_extracted_structure` | 字节变了，而每个 block 指纹都相同。 |

第三个才是诚实的那个。它**多半**是注释或排版 —— 但这些 parser 是**结构抽取**，不是文法解析，
所以一个发生在它建模不到的构造里的真实改动，从这里看起来一模一样。把它叫「仅文档变更」
是在按最舒服的方式读一份**支持不了这个结论**的证据，所以它不叫那个：
行数与注释数并排报出来供人判断，判词仍然是「去看」。**一份 drift 报告是去读 diff 的理由，绝不是放行。**

`iaiops program history` 列出在跟踪的程序；`iaiops program compare <name> <before> <after>`
比两个已存快照。删历史是 `iaiops program forget`，**只在 CLI** —— 删变更控制证据不该离 agent
只有一次调用。**不做任何自动清理。** 身份用**名字**不用路径：工程师站每开一次导出目录就换一个，
程序没换；不给 `--name` 时用文件名主干，并在输出里说明用的是哪一种。全程不碰设备 ——
读的是人导出来的文件。

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
- **制药**(`IAIOPS_MCP=pharma`,bacnet+modbus+hart+opcua):**不新增任何协议** —— 这正是重点:
  制药没有专用现场协议(洁净室跑 BACnet、制水跑 Modbus/HART、灌装冻干跑 S7、DCS 跑 OPC-UA,全在基座里),
  缺的是**语义**。版工具 `cleanroom_pressure_cascade`(Annex 1 压差级联,**逐门**判;相邻关系由人声明,
  不从房间清单里猜)、`cleanroom_particle_check`、`pharma_water_check`(USP <645> stage-1 **程序**:
  未温度补偿读数、测得温度**向下**取档、超限报「转 Stage 2」而不是 FAIL)。
  **不内嵌任何药典限值** —— 限值属于贵厂在其药典版本下已确认的质量标准,本仓无人能核的转录数字
  不该去决定一批环境算不算合格,而且抄松了读起来正好像「符合标准」。没声明的项报 `no_limit` /
  `not_graded` 并点名,**绝不当作通过**。已知缺口(写在该 edition 的 skill 里):没有 PI 连接器、
  S7 无真机验证、尚无 GxP(Annex 11 / Part 11)对照、LIMS/QMS **有意不做**(走 REST/DB 不走现场协议)。
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
- **Agent 技能**:仓库随附一个路由技能(`skills/iaiops`)+ **十个**按行业技能(`iaiops-fab` / `iaiops-factory` / `iaiops-process` / `iaiops-building` / `iaiops-water` / `iaiops-warehouse` / `iaiops-clinical` / `iaiops-pharma` / `iaiops-renewables` / `iaiops-plcnext`),把 agent 路由到正确的 MCP server 并说明工具面。

### 10. ISA-18.2 报警洪泛分析 + 合规报告(0.9 新增)

`alarm_flood_analysis`(洪泛片段/抖动报警/常驻报警/合理化 worksheet,CLI `iaiops diag alarm-flood|alarm-worksheet`);`iaiops compliance report`(等保 2.0 二/三级状态 + IEC 62443 FR1–6 对照 + 诚实差距清单,md/html)与 `iaiops compliance evidence`(审计证据 zip,哈希链校验)。辅助整改,非认证。

### 11. 数据导出 + Prometheus/Grafana 桥(0.9 新增)

`iaiops export csv|sqlite|parquet` 从本地 SQLite 存储按时间/端点/tag 过滤导出(Parquet 需 `iaiops[export]`);`iaiops metrics serve --port 9184` 暴露 Prometheus `/metrics`(默认只绑 127.0.0.1),Grafana 配方见 `docs/GRAFANA.md`。

### 12. 信创 / 国产时序库下沉

`historian_push` 把任意 connector 归一化后的数据写入本地 SQLite 或国产时序库 **TDengine** / **IoTDB**(不自建库、不绑 InfluxDB)。`compliance_mapping` 对照《工控系统网络安全防护指南》给诚实的逐项状态;`compliance_frameworks` / `compliance_dengbao_levels` 给等保 2.0 + IEC 62443 对照与二/三级增量。

---

## 安全与治理

- **读优先**:**194 个受治理工具 = 181 只读 + 10 个 MOC 设备写 + `historian_push`(也是写,但写的是历史库不是设备,`[WRITE][risk=low]`)+ 2 个已弃用别名**(每版工具只在选中对应 edition 时加载,故裸协议/单 edition 面比该全线总数小);读侧新增两层厂商 REST **只读**面——BAS 控制器层(Metasys/Niagara,building 版)与 Ignition Gateway MES/SCADA 层(factory 版);10 个写/命令工具(`s7_write_db`、`mc_write_words`、`fins_write_words`、`mqtt_publish`、`eip_write_tag`、`ethercat_write_sdo`、`ethercat_set_state`、`profinet_dcp_set`、`bacnet_write_property`、`bas_command`)全部 `[WRITE][risk=HIGH][MOC]`(`bas_command` 默认关闭 + 生命安全对象 denylist)。
- **破坏性操作**:dry-run 默认 + 双重确认 + MOC 门控 + 需记录审批人(一次性 `iaiops approve` 令牌;未配置 `risk_tiers` 时 high/critical 默认 `dual` 层);**10 个写工具全部声明 undo**(0.20.3 起无豁免),成功的写捕获改前值/状态并登记逆操作描述符。逆操作**在真没有逆的情况下如实返回「无」**——瞬时(`retain=False`)的 `mqtt_publish` 发出去就收不回;`ethercat_set_state` 的 `+ERR`/`NONE`/`BOOT` 不是可重新请求的干净 AL 状态。**一个过度承诺的 undo 比没有 undo 更糟**,因为总会有人把它重放到活的设备上。
- **治理 harness**:每个工具都过策略预检(策略引擎 fail-closed)+ 预算/失控熔断 + 风险分级 + 审计落库 `~/.iaiops/audit.db`(SHA-256 哈希链防篡改 + `iaiops audit verify`;高危写在审计不可用时拒绝执行);任何注册工具缺治理标记,MCP server 拒绝启动。**审计状态如实反映结果**(0.20.3):工具不抛异常而是返回规范 `{error, hint}` 信封,过去会被记成 `status='ok'`——失败的写和成功的写在轨迹里无法区分,熔断器也被告知「成功」;现已识别该信封记 `error`。**失控窗口计入被拒绝的重试**(0.20.3):上限不计拒绝(它没干活),但一个不理解拒绝、无限重试的调用方是最常见的卡死循环,过去完全拦不住(实测 500 次被拒高危写、上限 10、零拦停)。
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
