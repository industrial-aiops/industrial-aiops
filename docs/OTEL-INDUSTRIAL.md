<!-- Design note — how Industrial-AIOps positions itself relative to the OpenTelemetry Industrial
     community. Same honesty discipline as MARGO-ALIGNMENT.md: role mapping, concrete gap,
     contribution plan. Nothing here is a claim of compatibility — iaiops has zero OTel code today. -->

# Industrial-AIOps × OpenTelemetry Industrial — 生态对齐（设计说明）

> **草案 v1 · 2026-08-07 · 内部文档**
> 姊妹篇：`industrial-aiops/docs/MARGO-ALIGNMENT.md`（Margo 边缘互操作）
> **诚实状态：iaiops 目前零 OTel / OTLP 代码**（`grep -i "opentelemetry|otlp|otel"` 全仓零匹配）。本文全部为 roadmap `⏳`。

---

## 1. 为什么这件事突然重要：Margo 强制要求 OTel

关键事实（2026-08-07 核实）：

> **每台 Margo 合规设备 MUST 运行一个 OpenTelemetry Collector；metrics / logs / traces 经 OTLP 导出。**
> 但规范**不规定这些信号去哪**——exporter 配置留给最终用户。
> 来源：[javatask.dev — What Margo Actually Specifies](https://javatask.dev/blog/margo-reading-the-standard-part-1-what-margo-specifies/)

含义：OTel 对 iaiops 不是「一个可选生态」，而是 **Margo 路线上必然存在的既有基础设施**。
`MARGO-ALIGNMENT.md` §4.4 的 `⏳ Conformance run` 走通的那一天，脚下的设备一定有一个 OTel Collector 在跑。

---

## 2. 社区现状（2026-08-07 实测，勿当既成事实使用）

| 项 | 状态 |
|---|---|
| 成立 | **2026 年 5 月**（三个月） |
| 组织形式 | 社区自发 user group；**在 OTel 内部尚未正式化**（"user group" 概念本身还在讨论） |
| 规模 | 60+ 成员（材料口径）；`otel-industrial-community` 仓 **5 commits · 3 stars · 3 issues · 0 PR** |
| 例会 | **每月最后一个周四 10:00 ET**，公开 Google Doc 纪要 |
| Slack | CNCF `#otel-industrial` |
| 许可 | Apache-2.0 |

### 2.1 项目成熟度（全部早期）

| 项目 | 状态 | 作者 |
|---|---|---|
| Modbus Receiver | Experimental | lukaszciukaj |
| OPC UA Receiver | Experimental | bruegth |
| MQTT Sparkplug Receiver | Active Dev | jmacd |
| mqtt2otel（桥接） | Experimental | OSgAgA |
| EtherNet/IP Receiver | Work in Progress | Community |

**没有一个是 stable。** 且**列表里没有 SECS/GEM、HART、BACnet、MC、FINS、IO-Link、EtherCAT** —— iaiops 全都有。

### 2.2 全部三个开放 issue

| # | 标题 | 作者 / 日期 |
|---|---|---|
| 1 | **Community Roadmap 2026–2027** | luke6Lh43 · 2026-06-23 |
| 2 | Collect documentation from PLC manufacturer | bruegth · 2026-06-25 |
| 3 | Contact PLC manufacturer to inform them about this community | bruegth · 2026-06-25 |

> **⚠️ 修正一个此前的判断**：语义约定（semantic conventions）**工作尚未启动**——没有 issue、没有 PR、没有工作组。
> 材料第 9 页讲的是「为什么需要」，不是「已经在做」。
> 这意味着：**没有现成线程可加入，只能自己起**。窗口更大，但也需要主动提案而非跟随。

### 2.3 白皮书

`github.com/lukaszciukaj/industrial-observability-whitepaper`（Apache-2.0）

- **2026 版为 Lukasz Ciukaj 独著**，七章：执行摘要 / 可见性问题 / 标准对比 / OpenTelemetry（含 Caspar Water Project 案例）/ 结论 / 作者 / 参考。
- **2027 版明确开放共创**，点名欢迎：修订、**协议实现**、**案例研究**、新用例、图表、翻译。
- 贡献路径：GitHub Issue 提修订、PR 直接改（不必等年度发布）。

---

## 3. 层次划分：为什么不是竞品

```
┌──────────────────────────────────────────────────────────────┐
│  后端 / 可观测性平台（任意 OTLP 兼容后端）                      │
├──────────────────────────────────────────────────────────────┤
│  OTel Collector — 遥测数据平面                                 │  ← OTel Industrial 的赛道
│    receivers（Modbus/OPC-UA/Sparkplug/EIP…）→ processors →     │     Margo 设备强制存在
│    exporters；解决「数据怎么流出去」                             │
├──────────────────────────────────────────────────────────────┤
│  iaiops — 治理与诊断控制面                                     │  ← 我们的赛道
│    governance harness（审计链 / MOC / risk-tier / undo）        │
│    归一化模型（Tag / Sample / AssetNode ISA-95 / Alarm ISA-18.2）│
│    跨协议脑（RCA / 报警洪泛 / 数据质量 / 基线 / OEE）             │
│    受治理的 MCP 工具面；解决「AI 怎么安全地读与判断」              │
└──────────────────────────────────────────────────────────────┘
```

**OTel Collector 不做**：RCA、MOC 门控、审计哈希链、dry-run、undo、MCP 工具面、跨协议根因关联。
**iaiops 不做也不该做**：通用遥测管道、后端存储、dashboard。

---

## 4. 「不重造，从既有的里读」—— 第三次出现

这是 iaiops 已经做过两次的同一个架构决策：

| 场景 | 红海在位者 | 错误做法 | 本线决策 |
|---|---|---|---|
| 历史库 | PI / AVEVA | 自造时序库 | **P6 / A7 / D1**：不做 historian，tap 在旁边，只读读回 |
| Fab EDA | Cimetrix / PEER Group | 自建 E120/E125/E132/E134 栈 | **F2**：不做 EDA 栈，从既有基础设施读 |
| **遥测管道** | **OTel Collector（Margo 强制）** | **自建采集分发** | **本文**：不做 Collector，**往它写（OTLP exporter）+ 从它读（证据源）** |

---

## 5. 工作项（roadmap `⏳`）

### 5.1 `⏳` OTLP exporter —— 写出去

- 位置：`iaiops/core/sink/otlp.py`，与既有 `prometheus.py` / `iotdb.py` / `tdengine.py` 平级。
- 打包：`iaiops[otlp]` optional extra，懒加载，遵循既有 extras 纪律。
- **只做 exporter，不做 receiver。** receiver 是 OTel Industrial 的赛道，且会免费、会进官方发行版——与 **I9「不重造 Kepware 驱动覆盖」** 同一逻辑。
- 验证纪律：对真实 Collector 跑通才算 verified；mock 只能算软件自测。

### 5.2 `⏳` OTel 作为 RCA 证据源 —— 读回来

- 在 Margo 站点上，Collector 已经在采数据。`downtime_root_cause_live` 可以把它当作**又一类证据源**，与 `historian_query`（A7/D1）同构。
- 复用既有的「事故前窗口 + 引用来源/窗口/样本数」模式。
- **前置**：需确认目标站点的 Collector 有可查询的后端（Collector 本身不存储）。

### 5.3 `⏳` 语义约定提案 —— 最高战略价值

见 §6。

### 5.4 `⏳` 白皮书 2027 贡献

候选内容（均为已有资产，边际成本低）：
- **协议实现**：SECS/GEM、HART-IP、BACnet、MC、FINS、IO-Link —— 白皮书 2026 版的标准章节未覆盖这些。
- **案例研究**：跨协议 RCA / ISA-18.2 报警洪泛分析 / 数据质量看门狗。
- **可复现验证配方**：`VERIFICATION-RECORD.md` 里的容器 recipe（socat PTY 串口、bacpypes3 虚拟设备、真 asyncua、IoTDB/TDengine 容器）—— 正是社区第 10 页求助的 "testing environments"。

---

## 6. 语义约定：为什么这是最划算的一件事

材料第 9 页说明了需要，第 10 页明确求助 **"contributors with hands-on experience in industrial automation, OT environments, and industrial protocols"**。
而工作**尚未启动**（§2.2）——这是定义阶段，不是适配阶段。

### 6.1 iaiops 手上现成的资产

| 社区需要的 | 本线已有的 | 位置 |
|---|---|---|
| 跨协议统一数据模型 | `Tag / Sample / AssetNode(ISA-95) / Alarm(ISA-18.2)` | `core` 归一化模型 |
| tag 语义分类 | 温度/压力/流量/设定值/报警/状态 + 水行业专用（溶解氧/ORP/余氯/氨氮/跨膜压差） | `core/brain/semantics.py` |
| 跨协议资产建模 | `cross_protocol_asset_model` · `adopt_alias_map` · `diff_alias_map` | `mcp_server/tools/asset_model_tools.py` |
| 数据质量语义 | 双时间戳 + quality + 来源；staleness / flatline / 心跳为一等公民；**绝不静默插值** | `core/brain/dataquality.py` |
| 协议广度实证 | 14 种协议，含社区列表里完全没有的 6 种 | `iaiops/connectors/` |

### 6.2 提案要点（建议内容）

1. **双时间戳是强制项，不是可选项。** 设备侧时间戳与采集侧时间戳必须分开表达；两者不可互相冒充。这是 OT 与 IT 遥测最本质的差异之一。
2. **quality 是一等公民。** OPC-UA 有 StatusCode、HART 有设备状态、Modbus 什么都没有——语义约定必须能表达「质量未知」而不是默认 good。
3. **绝不静默插值 / 不有损压缩。** 约定应显式区分「实测样本」与「派生值」。
4. **资产层级对齐 ISA-95**（site / area / line / cell / equipment），报警对齐 **ISA-18.2** —— 不要另起炉灶，OT 侧已有既成标准。
5. **协议来源必须可追溯**：同一个物理量经 Modbus 与经 OPC-UA 采到，语义相同但可信度不同。

---

## 7. 边界与风险

| 项 | 判断 |
|---|---|
| **不做 receiver** | 他们的赛道；免费且会进官方发行版 |
| **brain 层不 OTel 化** | RCA 证据链、基线、MOC 审批、审计哈希链**不是遥测**，硬塞进 metrics/logs/traces 会失真。出口用 OTLP，内核保持自有模型 |
| **不押重注** | 社区 3 个月大、0 PR、未在 OTel 内部正式化。低成本参与 + 高价值卡位，不绑路线图 |
| **品牌隔离** | OpenTelemetry / CNCF / OTLP 属中立开放标准，与 IEC 62443 / 等保 / Margo 同档，判断为可入 OT 仓。**须按 CLAUDE.md 铁律自行复核** |
| **诚实纪律** | 在真实 Collector 跑通前，任何材料不得声称「OTel 兼容」 |

---

## 附录 — 可直接粘贴的提案

### A. 回复 issue #1（Community Roadmap 2026–2027）

> **Proposing semantic conventions as a 2026 workstream — with an existing cross-protocol model to start from**
>
> I maintain **Industrial-AIOps** (`iaiops`, MIT, on PyPI + the MCP Registry) — a vendor-neutral,
> read-first OT data tap across 14 field protocols (OPC-UA, Modbus TCP/RTU, S7comm, Mitsubishi MC,
> Omron FINS, EtherNet/IP, EtherCAT, PROFINET-DCP, MTConnect, MQTT/Sparkplug B, **SECS/GEM**,
> **HART-IP**, **BACnet/IP**, **IO-Link**) plus a cross-protocol diagnostic layer.
>
> Looking at the roadmap issue and the July Margo presentation: semantic conventions are named as a
> need but I can't find a workstream for them yet. I'd like to propose starting one, and I can bring
> a concrete starting point rather than a blank page.
>
> **What we already run in production shape:**
> - A normalized cross-protocol model — `Tag` / `Sample` / `AssetNode` (ISA-95 site/area/line/cell/equipment)
>   / `Alarm` (ISA-18.2). Connectors normalize *into* it; the analytics layer operates *on* it, so the
>   same OEE / RCA / data-quality logic runs regardless of the source protocol.
> - A heuristic tag semantic classifier (temperature / pressure / flow / setpoint / alarm / state,
>   plus domain vocabularies such as water treatment: DO, ORP, residual chlorine, transmembrane pressure).
>
> **Five things I'd argue the conventions must get right, from field experience:**
> 1. **Two timestamps are mandatory, not optional** — device-side vs collection-side. Neither may
>    impersonate the other. This is one of the sharpest OT/IT telemetry differences.
> 2. **Quality is a first-class field** — OPC-UA has StatusCode, HART has device status, Modbus has
>    nothing. The convention must be able to say "quality unknown" rather than defaulting to good.
> 3. **Never silently interpolate or lossily compress** — measured samples and derived values need to
>    be distinguishable in the data model itself.
> 4. **Reuse ISA-95 for asset hierarchy and ISA-18.2 for alarms** — OT already has these; a parallel
>    vocabulary would fragment rather than unify.
> 5. **Protocol provenance must survive** — the same physical quantity read over Modbus vs OPC-UA
>    carries different trust characteristics.
>
> Happy to write this up as a proper proposal, or to contribute to whatever shape the community
> prefers. Also worth noting the project list has no SECS/GEM, HART, BACnet, MC, FINS, IO-Link or
> EtherCAT coverage yet — I have working read paths for all of those and am glad to share what the
> data models look like in practice.

### B. 白皮书 2027 贡献提案（GitHub Issue）

> **Offering: protocol coverage + reproducible verification recipes for the 2027 edition**
>
> Read the 2026 edition — the framing of why OT resists instrumentation matches what we see. Two
> things I can contribute for 2027:
>
> **1. Protocol coverage the standards chapter doesn't reach yet** — SECS/GEM (SEMI E5/E30/E37, the
> entry ticket for semiconductor and display fabs), HART-IP, BACnet/IP, Mitsubishi MC, Omron FINS,
> IO-Link. I maintain read paths for all of them and can write them up with the same structure the
> existing chapter uses.
>
> **2. Reproducible verification recipes** — the community asks for test environments. We run a
> discipline of "software-verifiable everything, honestly labelled" and have working setups that
> need no vendor hardware: a real `socat` PTY pair + pymodbus RTU server for serial Modbus, a real
> `bacpypes3` virtual BACnet/IP device, an in-process `asyncua` server with historical access, and
> Docker containers for IoTDB/TDengine round-trips. These are exactly the "local test environments
> for validating receivers" the community deck asks for, and they cost nothing to reuse.
>
> Both are Apache-2.0-compatible on our side (project is MIT). Happy to open PRs directly rather than
> wait for the annual cycle, per the contributing note.

### C. 加入步骤（需人工执行）

1. **CNCF Slack** → `https://slack.cncf.io/` 注册后加入 `#otel-industrial`。
2. **月会** → 每月最后一个周四 10:00 ET，日历与议程见 `otel-industrial-community` 仓的会议纪要 Google Doc。
3. **身份** → 全部使用 **wei `<zhouwei008@gmail.com>`**（CLAUDE.md 铁律）。
