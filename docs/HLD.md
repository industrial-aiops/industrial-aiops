# Industrial-AIOps (iaiops) — 高层设计 (HLD)

> 单一架构真相文档。此前 `CLAUDE.md` 指向的 `docs/HLD.md` / `docs/PLATFORM-ARCHITECTURE.md`
> 均不存在；本文件补上并成为权威来源。身份、品牌隔离、铁律见 `CLAUDE.md`。

## 1. 定位

厂商中立的**工业数据 tap + 跨协议智能排查**。唯一带**审计 + 预算 + 回滚 + 分级审批**
的 OT 运维工具线。核心承诺一句话：

> **数据采集与操作要准确、高效；每一次调用都留下不可绕的审计。**
> 读/写**授权**不由 tap 承担 —— 那是 agent 判断或账号/权限管理的职责。

## 2. 四层架构

```
┌───────────────────────────────────────────────────────────────┐
│ Front-ends（前端边界，各自受治理）                              │
│   • mcp_server/  —— 菜单式 MCP：@mcp.tool() 包装，按 IAIOPS_MCP  │
│                     profile 暴露；两道注册期 posture 门          │
│   • iaiops/cli/  —— Typer CLI：每条命令一个受治理边界            │
├───────────────────────────────────────────────────────────────┤
│ core/governance/ —— 治理主干（两个前端共用同一引擎）            │
│   @governed_tool = 策略 + 审计 + 预算 + 风险分级 + 审批 + 回滚   │
├───────────────────────────────────────────────────────────────┤
│ core/brain · core/runtime —— 跨协议分析（只读、纯函数、advisory）│
│   + 归一化数据模型 + 连接/配置/信封                             │
├───────────────────────────────────────────────────────────────┤
│ connectors/<protocol>/ops.py —— 纯协议层                        │
│   接收已解析的 target 对象 + 操作参数；不含治理、不含 endpoint 名 │
└───────────────────────────────────────────────────────────────┘
editions = skills/<edition>/  按行业打包 + 各自 signature 工具
```

**层间调用**：`mcp 包装` 与 `cli 命令` 都持有 `endpoint` 名 → 解析成 `target` →
调 `connectors/*/ops.py`。**endpoint 名只存在于前端边界**，进入 ops 后只剩已解析对象。

## 3. 治理主干 `@governed_tool`

`iaiops/core/governance/decorators.py`。挂在**前端边界函数**上，一次调用跑一次：

| 职责 | 说明 |
|---|---|
| 策略预检 | deny 规则、维护窗口 |
| 审计 | 每次调用写 `~/.iaiops/audit.db`（参数脱敏 + 控制字符清洗 + 密钥擦除） |
| 审计健康门 | high/critical 在审计不可写时**拒绝**（fail closed）；low/medium 只读放行并告警一次 |
| 预算 / 失控保护 | 上限按「干的活」计（次数与时长，拒绝不计）；失控窗口按 `(tool, params)` 计，**拒绝也计** |
| 分级审批 | high/critical 需要**已记录的审批人**（一次性 token 优先，静态 env 兜底） |
| 回滚 | 成功的写捕获逆操作到 `~/.iaiops/undo.db`，结果带 `_undo_id` |

**审计状态必须反映真实结果（0.20.3）。** 工具不抛异常——MCP 层把每个异常转成规范的
`{error, hint}` 信封，于是治理包装器看到的是一个正常返回值，曾把失败的调用记成
`status='ok'`。两个后果：审计轨迹分不清「写成功」和「PLC 连不上」；`_finalize` 用
`success=(status=='ok')` 汇报给 pattern 熔断器，**一个每次都失败的 armed pattern 被汇报成每次都成功**。
现在识别该信封并记 `status='error'`，同时跳过失败调用的 undo 计算。识别范围刻意收窄：
只认信封的两种结构形态且 `error` 为非空字符串——诊断工具返回 `error: None`、结构化
`{code, text}`、或含一行错误的多行结果都不算失败。

**失控窗口必须看得见被重试的拒绝（0.20.3）。** 上限与失控窗口是两条轴，一次策略拒绝把它们分开：
被拒绝的调用免于上限是对的（它没干活，一条配错的 deny 规则不该耗光操作员预算），但失控指纹
过去只记在放行路径上，于是熔断器能看见所有循环、唯独看不见**最可能的那一种**——一个不理解
拒绝、于是无限重试的调用方（LLM agent 最容易产生的失控形态）。实测：500 次相同的被拒高危写、
上限 10、零次拦停。现在拒绝计入窗口且**只**计入窗口；窗口填满后熔断器的 `BudgetExceeded`
取代那次拒绝（此时调用方需要的是「别再叫了」而不是第 26 条「被拒绝」），并审计成
`budget_exceeded`，使操作员能区分「被拒绝」与「被拒绝后不肯停」。

**scoping 依赖 endpoint 名**：策略、审批分级都按 endpoint 匹配。这是治理必须留在
**前端边界**（endpoint 名仍在）、而**不能**下沉到 ops 层（只剩已解析 target）的根本原因。

### 3.1 双前端、单引擎（本轮的核心不变量）

MCP 与 CLI 是两个独立前端，**没有任何一次调用同时穿过两者**。因此：

- **每个前端在自己的边界各自受治理**（各挂一次 `@governed_tool`），
- **共用同一个治理引擎**（同一个 audit.db / policy / budget）。

于是 `iaiops ethercat write-sdo --apply`（CLI 写）与 `ethercat_write_sdo`（MCP 写）
产生**形状一致**的审计行。任一前端都无法绕过审计。

写操作用**按实际效果定级**（effect-based risk），**两个前端一致**：dry-run 预览
按 `low` 审计——它什么都不改，故不需审批人，预览一次写不该先去领 token；真正的写按
`high`——审计 + 审批门禁（MOC）。两者都留审计行。机制在共享的 `@governed_tool`
（`preview_param`）里：MCP 写工具用 `preview_param="dry_run"`（`dry_run` 为真=预览），
CLI 写命令用 `preview_param="apply", preview_truthy=False`（`apply` 为假=预览）。
该参数**默认关闭**，故 iaiops-energy / iaiops-enterprise 等复用本装饰器的仓库行为不变，
除非它们也接入。

> 曾经的缺口（已在本轮修复）：`@governed_tool` 只挂在 MCP 包装上，CLI 直接调 `ops.*`，
> 导致 **CLI 写操作零审计**。修复 = 给 CLI 命令边界同样挂治理。

## 4. MCP 注册期 posture 门（与读写授权正交）

两道门在注册后、`assert_all_tools_governed()` 前运行，**把工具从注册表删除**（而非调用时拒绝），
因为弱模型/被注入的模型能调用它**看得见**的任何工具，而一次 OT 写不可逆：

| 门 | env | 依据 | 语义 |
|---|---|---|---|
| **no-egress** | `IAIOPS_NO_EGRESS=1` | `_egress` | 删掉"把数据发出盒子"的工具（airgap/密闭部署） |

> **read-only 门（`IAIOPS_READ_ONLY`）已于本轮移除**。它把一个**读写授权决定**焊进了 tap，
> 与定位冲突（授权归 agent/账号管理）。移除后，**审计成为唯一扛得住的保证**，故同步补齐
> CLI 审计（§3.1）。no-egress 门保留 —— 它回答的是另一条轴"数据能否离开盒子"，属部署拓扑
> 保证，非读写授权。

## 5. 返回信封（弱模型友好，独立机制）

`iaiops/core/runtime/envelope.py`：给 list/bounded 结果统一附加截断元数据。与授权无关，保留。

## 6. 决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | 移除 read-only 门 | 读写授权非 tap 职责；焊进采集层是错位 |
| D2 | 保留 no-egress 门 | 正交轴（数据外泄/airgap），部署拓扑保证 |
| D3 | 治理留在前端边界，不下沉 ops | ops 层已丢失 endpoint 名，策略/审批 scoping 会失效 |
| D4 | CLI 命令边界补挂 `@governed_tool` | 双前端单引擎，审计不可绕，与 MCP 形状一致 |
| D5 | 保留 brain/connectors 中"read-only/非破坏性"**描述性**注释 | 描述行为，非被删功能 |
| D6 | **拒绝** MCP Tunnels（私网反向穿透） | 隔离是产品承诺本身，不是待解决的障碍 —— 见 §7.2 |
| D7 | **拒绝** 无状态传输 / 云托管横向扩；本地 stdio 是一等公民 | 协议会话天生有状态且昂贵；部署形态是现场边缘盒子，无横向扩需求 —— 见 §7.3 |
| D8 | Tasks 扩展 **defer**，设计先行 | 异步拆开了「调用—审计—结果」同步闭环，治理语义未定 —— 见 §7.4 |
| D9 | MCP Apps **有条件评估**，仅限「人在回路」场景 | 需 host 能渲 iframe；无人值守的边缘 agent runtime 用不上 —— 见 §7.5 |
| D10 | 治理不变量必须由**覆盖真实工具面**的契约测试守住，而非注释 | 合成函数上的测试全绿，真实写工具却可能在重构中丢掉 `risk_level="high"`；已实测：把 `s7_write_db` 降级会挂 3 条契约测试，而在补契约之前一条都不挂 |
| D11 | 被拒绝的调用免于**上限**、但计入**失控窗口** | 两条轴：上限给「干的活」计价（拒绝没干活，配错的规则不该耗光预算），失控窗口探测卡死循环（重试拒绝正是最常见的那种） |
| D12 | 「某依赖不可 CI 构建」是**有保质期的测量**，不是属性 | `pydnp3` 被当作不可构建数月（实为 2019 绑定层三处机械问题），`pyiec61850` 早已能跑却无人回头核对 —— 重复该结论前必须重测；且 live 测试被 skip 必须让构建变红 |
| D13 | open-core 分界 = **单次调用的能力**留 MIT，**组织与时间维度的保证**归 `iaiops-enterprise` | 见 §8.3。分界依据是"问题属于谁"，不是"哪块值钱" —— 后者会把边界承诺逐次侵蚀成空话 |
| D14 | **拒绝**把已发布仓库转私有、**拒绝** relicense（BUSL/AGPL/SSPL） | MIT 不可撤销：转私有挡不住已发布的 0.22.0，只损失五个分发渠道。稀缺的是分发与责任承担，不是 connector 代码（协议层是开源库之上的薄壳，两周可重写） —— 见 §8.4 |
| D15 | 新功能**默认落 MIT**；进 enterprise 需 §8.3 判定为真且写进 `iaiops-enterprise/docs/ROADMAP.md` | 默认方向决定十年后的形状。默认收费 = 每次都要论证"为什么不收费"，边界必然漂移 |

## 7. MCP 协议版本立场（2026-07-28 spec）

### 7.1 没有 flag day —— 我们处在 opt-in 位置

MCP 有三个**各自独立、版本协商**的东西，不是一个整体：协议 spec（带日期的版本）、server 声明支持哪个版本、客户端/host 连接时协商。握手时双方谈妥一个都支持的版本 → 新旧共存。**"spec 升级了" ≠ "server 必须跟"。**

升级链条与我们的位置：

```
① spec 发布(2026-07-28, RC)  ②SDK 实现  ③host 支持  ④我们 opt-in ★  ⑤版本协商让新旧并存
```

在没有主动升 SDK、没启用新特性之前，①②③ 发生什么都不影响现有部署。**触发行动的只有我们自己的选择，不是外部强制。**

事实核对（2026-07-30 实测，勿凭转述）：Python SDK **`mcp 2.0.0` 已是正式版**（PyPI 2026-07-28 发布，`Development Status :: 5 - Production/Stable`，未 yanked），不是 beta —— "等 SDK GA 再升"这个条件**已经满足**。真正让我们不急的是别的：pin `mcp[cli]>=1.10,<2.0` 已挡住被动升级，且本次 stateless 类改动主要针对 Streamable HTTP，我们走 stdio 几乎不受影响。

⚠️ SDK v2 是唯一早晚要碰的**机械迁移**：`mcp.server.fastmcp` 模块已删除，`_GovernedFastMCP(FastMCP)` 在本仓与 `iaiops-energy` 都会 ImportError。但 `MCPServer.tool` 签名与 `FastMCP.tool` **逐字相同**，子类换一行基类即可；`ToolAnnotations` 字段改 snake_case 但 camelCase kwargs 仍被 pydantic alias 接受、wire 仍是 camelCase，故 `mcp_server/hints.py` 构造代码不变 —— **只有测试里的 `.readOnlyHint` 属性访问会断**。

### 7.2 D6 — 拒绝 MCP Tunnels

这条与 IT 线（`AIops-tools`）结论**相反**，必须显式记录，避免被跨线经验带偏。IT 线把私网反向穿透视为"够得着管理网"的关键钥匙；对 OT 线，网络隔离**是产品承诺本身**：

- `IAIOPS_NO_EGRESS` 在注册期就把外发类工具从 `list_tools()` 摘掉（§4）
- `deploy/airgap/compose.yaml` 是一等公民部署形态
- Margo 描述符写明 outbound-only、零入站端口
- 等保 2.0 / IEC 62443 分区分域交叉表

一条从 OT 网反向连出公网的隧道，正是上述整套要排除的东西。（Tunnels 本就是某托管平台的产品功能，不属于 MCP 协议。）

### 7.3 D7 — 拒绝无状态托管，本地 stdio 保持一等公民

两个独立理由：

1. **协议会话天生有状态且昂贵**：OPC-UA session、S7 连接、MQTT/Sparkplug 订阅、BACnet COV 订阅 —— `ConnectionManager` 存在的全部意义就是复用它们。无状态 = 每次调用重建会话，对老 PLC 是实打实的负担（部分设备连接数上限个位数）。
2. **部署形态本就不是云托管**：IGEL recipe / Margo edge app / airgap compose 全是"跑在现场那台盒子上"。一个厂一个 tap，不存在"一个端点服务整个团队"的横向扩需求。

**底线**：企业向复杂度（OAuth/OIDC、连接池、无状态）若将来引入，必须是**可选增量**，不得渗入本地/边缘路径 —— 否则破坏「弱模型/边缘模型兼容」这条家族级约束（§5）。OAuth 与 D1 不冲突（边界**认证**，非 tap 内**授权**），但 OT 现场常连不到 IdP（airgap 就是没有），故不得成为必需。

### 7.4 D8 — Tasks defer，四个治理问题先答

候选（真正耗时的操作，比 IT 线少得多 —— 绝大多数工具是读且快）：`monitor_changes`（bounded COV）、HART burst-listen、MTConnect stream、跨端点发现（PROFINET DCP / BACnet Who-Is / `asset_inventory`）、baseline 学习。**写操作不是候选** —— dry-run + MOC 审批的延迟是人的延迟。

动手前必须回答：

1. task 的审计行**何时**写？现有 `@governed_tool` 假设「调用—审计—结果」是同步闭环，Tasks 把它拆开了。
2. **取消一个已把写请求发到 PLC 的 task，语义是什么？** 协议层已发出的帧收不回来，undo 捕获的 before 状态还算不算数？
3. budget 在 task 生命周期哪个点扣？
4. effect-based 风险降级（`_effective_risk_level`，preview 走 low）在异步下如何表达？

审计的不可绕过性是本产品线的核心承诺（D1/D4）。**设计未定不写实现。**

### 7.5 D9 — MCP Apps 有条件评估

本次 spec 里**唯一**直接服务「边缘小模型」约束的能力：富内容渲染进沙箱 iframe，模型只拿紧凑摘要，大输出不再逐 token 灌 context。候选是报表类只读输出：RCA 叙述、OEE 报表、ISA-18.2 alarm Pareto、`asset_inventory` 全表、等保/62443 合规报告、historian 序列。

**前提陷阱**：需 host 能渲 iframe。「工程师用桌面客户端连现场 tap」有效；「边缘盒子上无人值守的 agent runtime」没有 UI，完全白搭。评估第一步是确认目标场景占比，别为用不上的形态做工程。

**不要指望它解决工具数问题** —— 本次 spec 对「工具数 / 选对工具的准确率」一字未提，那条杠杆仍是 `EDITION_MODULES` 菜单式 profile。

## 8. 商业分层与开源边界（open-core）

架构分层（§2）回答"代码放哪"，本节回答**"功能归哪个仓、按什么授权"**。这条线一旦
含糊，它会被每一次"这个好像能卖钱"逐次侵蚀，最终把 §8.2 的承诺变成空话 —— 所以
判定规则写在架构文档里，和治理不变量同级。

> 本节只写**边界与归属**（公开、对用户的承诺）。定价、市场、销售路径属于商业策略，
> 不进本仓 —— 见私有仓 `iaiops-enterprise/docs/COMMERCIAL.md`。

### 8.1 三层

| 层 | 载体 / 授权 | 内容 | 形态 |
|---|---|---|---|
| **Community** | 本仓 + `industrial-aiops-energy`，**MIT** | tap 能力全集：12+ 协议的读**与写**、治理主干（审计/预算/回滚/审批 token/posture 门）、brain 跨协议分析、全部 edition skills | 五渠道公开分发（PyPI · GitHub · MCP registry · SkillHub · Glama） |
| **Enterprise** | `iaiops-enterprise`，**proprietary** | 围绕写的**组织工作流与可交付凭证**：n-of-m 审批、签名审计证据、合规证据报告、留存归档、fleet、license | 私有 wheel / 私有 index，随支持合同交付 |
| **Project** | 非软件 | 现场接入、点表梳理、验收报告、版本 pin 与兼容承诺 | 人天 |

**Enterprise 不是"功能更多的 iaiops"**，它是支持合同的技术载体：买方买的是**责任与可交付
的证明**，软件只是它的形状。这也是为什么 §8.3 的判定标准是"问题属于谁"而非"哪块值钱"。

### 8.2 不可退让的边界承诺（已在 `iaiops-enterprise/README.md` 公开）

1. **已开源的永不收回** —— MIT 基座的全部功能（**包括受治理的写工具**）永久开源可用；
   enterprise 层不 gate、不降级、不弱化基座。
2. **离线优先，永不 phone-home** —— license 是离线可验的 Ed25519 文件；企业功能在气隙内完整可用。
3. **过期不 brick** —— 30 天宽限，之后仅企业功能给 teaching error；开源基座不受任何影响。

第 1 条在 OT 语境下不是姿态而是准入条件：现场买方最怕关键路径被厂商卡脖子，反悔一次，
这条产品线的可信度归零。**写路径 100% 复用开源治理链**（dry-run → 一次性 token → undo →
审计），enterprise 只决定"token 由谁、按什么流程铸出"。

### 8.3 新功能归属判定（唯一规则）

按顺序问，命中即停：

1. 它让 tap **读到/写到**一个新的设备、协议、数据点或分析结论吗？→ **MIT**。永远。
2. 它让**某一次调用**变得可审计、可回滚、可预算、可分级吗？→ **MIT**。治理主干是基座
   的定位本身（§1），不是增值项。
3. 它解决的是**多个人 / 多个站点 / 多个月**的问题吗？—— 谁有资格批、谁签名背书、
   跨站怎么统一、留存多久、最后交给**外部第三方**（审计方/测评机构/监管）看什么？
   → **enterprise**。
4. 以上都不是 → **MIT**（默认方向，见 D15）。

一句话：**单次调用的正确性归 MIT；组织与时间维度的保证归 enterprise。**

明确**不得**迁入 enterprise 的东西（迁入即违反承诺 1）：任何协议 connector、任何
`risk_tier` 分级、审计写入本身、undo 捕获、dry-run、posture 门、返回信封、edition skills。

边界上的两个真实判例：

- **合规交叉表 vs 合规证据报告** —— `core/brain/compliance*.py` 描述的是"**产品**如何对上
  等保 2.0 / IEC 62443"，与本站运行数据无关，是自评/onboarding 材料 → **留 MIT**。
  而"**本站** 在过去 90 天里发生了 N 次写、每次都有 2 名具名审批人、哈希链完整、由站点
  密钥签名"是一份可交给第三方的**背书**，属规则 3 → **enterprise**。同一份交叉表，
  两种产物，不冲突。
- **审计转发 vs 可靠投递** —— `iaiops audit forward`（syslog UDP / HTTP，best-effort、
  at-least-once、无 ACK）是单次调用之后的顺手动作 → **留 MIT**。"六个月不丢一条"是
  留存承诺，属规则 3 → enterprise。
- **现场勘察（scan）的两个前端** —— 扫描引擎、`iaiops scan` CLI、本地 SQLite 存储、
  未签名 HTML 报告全部 **留 MIT**（规则 1：它让 tap 读到一台此前不知道的设备）。
  跨时间的快照比对、跨站点汇总、以及**给第三方看的签名报告**属规则 3 → enterprise。
  **scan 的 MCP 前端也在 enterprise**，这是本条唯一需要解释的地方：它看起来像"把一个
  MIT 能力的入口收进付费层"，但并不违反承诺 1 —— 能力（库 + CLI）完整留在 MIT 且可
  独立使用，MCP 只是第二个前端；而 scan 按定位就是**零 AI、离线**的产品（边缘侧不跑
  大模型），agent 前端服务的是办公室侧而非现场侧。若哪天现场侧真的需要 agent 驱动
  扫描，按 D15 默认方向应当落回 MIT。

### 8.4 D14 —— 为什么不转私有、不 relicense

三条独立理由，任一成立即足够：

1. **收不回来。** MIT 授权不可撤销：0.22.0 及此前所有版本，任何人可永久 fork、商用、
   闭源分发。转私有只影响未来提交。
2. **代价与收益反向。** 稀缺的是"被五个渠道搜到 + 被 LLM 装上 + 有版本 pin 和支持矩阵
   的承担者"，不是 connector 代码 —— 协议层是 `asyncua`/`pymodbus`/`snap7` 之上的薄壳，
   一个懂 OT 的人两周可重写。转私有 = 丢掉唯一稀缺的，换回不稀缺的。
3. **BUSL/AGPL 解决的是"被白嫖"，当前问题是"没人用"。** 加限制会同时压住 MCP 生态与
   Margo/IGEL 那条路。等出现真实的商业抄袭再重议 —— 届时受影响的也只是**新增**代码。
