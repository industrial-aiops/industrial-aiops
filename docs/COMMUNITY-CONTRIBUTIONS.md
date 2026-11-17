# 社区贡献与 PR 跟踪台账

最后核对：2026-11-17 17:33:41（Asia/Shanghai）。

只读 GitHub API 快照；不是实时状态，也不是账号全部活动清单。
合并按 merged_at 判断，closed 不自动算合并；自身 PR、他人承接 PR、
上游 issue/comment 与未外投草稿分开记录。没有把已提交等同于社区认可或认证。

重要更正：zw008 已有 Tahu #472、Margo CTT #16/#20 等外部提交。
此前本聊天中“尚未向外部提交”的概括不完整，应以本台账核对结果为准。

## 本人提交的上游 PR

| 项目与记录 | 内容 | 当前状态 | 参与身份 | 下一步 |
|---|---|---|---|---|
| [margo/conformance_test_toolkit #16](https://github.com/margo/conformance_test_toolkit/pull/16) | CTT 报告记录应用包来源 | merged | author; GitHub 作者 zw008 | 已合入 dev；通过 #17 跟踪 main 的承接 |
| [margo/conformance_test_toolkit #20](https://github.com/margo/conformance_test_toolkit/pull/20) | 修复 Compose OTEL 参数插值和默认值解析 | merged | author; GitHub 作者 zw008 | 固定新提交重跑 CTT，不改写历史失败结果 |
| [eclipse-tahu/tahu #472](https://github.com/eclipse-tahu/tahu/pull/472) | Python addMetric 默认时间戳按调用时计算 | open | author; GitHub 作者 zw008 | 跟进 review/CI，与 #398 去重，不开重复 PR |

## 相关承接 PR（不是本人提交）

| 项目与记录 | 内容 | 当前状态 | 参与身份 | 下一步 |
|---|---|---|---|---|
| [margo/conformance_test_toolkit #17](https://github.com/margo/conformance_test_toolkit/pull/17) | 他人发起的 dev→main 汇总，包含 #16 | merged | related; GitHub 作者 nitparihar | 不是本人提交；核对实际运行版本 |

## 上游 issue 与讨论参与

| 项目与记录 | 内容 | 当前状态 | 参与身份 | 下一步 |
|---|---|---|---|---|
| [margo/conformance_test_toolkit #18](https://github.com/margo/conformance_test_toolkit/issues/18) | CTT 漏检 rc.3 Compose OCI 组件格式 | open | author; GitHub 作者 zw008 | 关注修复并准备错误包/修正包正反样例 |
| [margo/conformance_test_toolkit #19](https://github.com/margo/conformance_test_toolkit/issues/19) | OTEL 插值被误判为非 OTLP exporter | closed | author; GitHub 作者 zw008 | 关联已合并 #20；关闭不等于本地已重测 |
| [margo/sandbox #490](https://github.com/margo/sandbox/issues/490) | Compose 更新删除命名状态卷 | open | author; GitHub 作者 zw008 | 关注修复并验证审计、密钥及配置保留 |
| [margo/sandbox #491](https://github.com/margo/sandbox/issues/491) | 错误 servicePort 与 CLI 误报成功 | open | author; GitHub 作者 zw008 | 重跑拒绝参数，分别确认退出码与 WFM 状态 |
| [margo/specification #145](https://github.com/margo/specification/issues/145) | 参与敏感信息管理策略讨论 | open | commenter; GitHub 作者 ajcraig | 关注外部密钥引用与部署凭据边界 |
| [margo/specification-enhancements #66 comment](https://github.com/margo/specification-enhancements/pull/66#issuecomment-6730346103) | 补充 RS-485 冲突与资源预留用例 | posted; parent open | commenter; GitHub 作者 zw008 | 观察资源预留语义与维护者回应 |
| [margo/specification-enhancements #103 comment](https://github.com/margo/specification-enhancements/pull/103#issuecomment-6730348290) | 询问规范增强与部署衔接 | posted; parent open | commenter; GitHub 作者 zw008 | 核对后续回应和规范变更 |

## 自身仓库 PR（不计为外部贡献）

| 项目与记录 | 内容 | 当前状态 | 参与身份 | 下一步 |
|---|---|---|---|---|
| [industrial-aiops/industrial-aiops #295](https://github.com/industrial-aiops/industrial-aiops/pull/295) | 初始 eKuiper/Tahu 互操作试验 | draft | author; GitHub 作者 zw008 | 审查与后续试验重叠；Draft 不等于交付 |
| [industrial-aiops/industrial-aiops #299](https://github.com/industrial-aiops/industrial-aiops/pull/299) | IGEL 基线、依赖下限、PKI 与社区清单 | merged | author; GitHub 作者 zw008 | IGEL/AGNES 与独立厂商 PKI 验证仍单列 |
| [industrial-aiops/industrial-aiops #300](https://github.com/industrial-aiops/industrial-aiops/pull/300) | 父节点 NDEATH 拒绝设备缓存、外部 Tahu 报文回归 | merged | author; GitHub 作者 zw008 | main 已有，尚未发布；扩展 broker 生命周期矩阵 |
| [industrial-aiops/industrial-aiops #301](https://github.com/industrial-aiops/industrial-aiops/pull/301) | Fledge 通知函数复现及 #300 状态同步 | merged | author; GitHub 作者 zw008 | 实际 delivery-plugin 入参与完整服务仍待验证 |
| [industrial-aiops/industrial-aiops #302](https://github.com/industrial-aiops/industrial-aiops/pull/302) | Fledge 上游文档草稿与 PIVOT Python 示例 | draft | author; GitHub 作者 zw008 | 审阅草稿；自身仓库 PR 不等于外部提交 |

## 未提交的外部草稿与候选

| 项目 | 内容 | 状态 | 下一步 |
|---|---|---|---|
| [Fledge](https://github.com/industrial-aiops/industrial-aiops/blob/feat/community-contribution-drafts/docs/community/contributions/fledge-notification-context.patch) | 可选 reason.data、单条数据和窗口聚合边界文档补丁 | not_submitted | 核对最新 develop，审阅后再明确执行外投；完整服务未验证 |
| [FledgePOWER / PIVOT](https://github.com/industrial-aiops/industrial-aiops/pull/302) | 三个模型 JSON 示例的 Python 无损读取与字段保留，不是 Schema 验证 | not_submitted | 围绕现有 #2 明确权威模型和目标 Python API |
| OPC Foundation / UA Cloud Library | #326 大值上传候选，未自建服务复现 | research_only | 在本地服务复现，不向公共实例上传实验 |
| SEAPATH | 只读监控工作负载候选，无部署实测或提交 | research_only | 有实验环境后再限定小场景 |

## 每次日常维护的跟踪顺序

1. 刷新状态，查看更新日期、review、CI 和维护者回复；避免重复提交。
2. 按待办重跑固定版本实验，记录命令、提交、证据和未验证边界。
3. 回应或修改前先准备可审阅结果；对外消息、PR、注册另行明确执行。
4. 合并后检查目标分支/发布版本是否包含变更，最后才更新本地验证结论。

刷新命令（需要 gh 已认证；只 GET，不提交或发送消息）：

```bash
python3 scripts/community/refresh_contribution_tracker.py --write
```

不加 --write 只输出 JSON 到标准输出。任何查询失败都不覆盖已有快照。
维护 contribution-registry.json 中的内容与下一步；状态保存在 contribution-snapshot.json。
新增参与记录应登记真实 URL；刷新不代替全账号活动发现，也不自动安排定时任务。
