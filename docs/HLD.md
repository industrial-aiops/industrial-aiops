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
| 预算 / 失控保护 | 累计次数与时长 |
| 分级审批 | high/critical 需要**已记录的审批人**（一次性 token 优先，静态 env 兜底） |
| 回滚 | 成功的写捕获逆操作到 `~/.iaiops/undo.db`，结果带 `_undo_id` |

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
