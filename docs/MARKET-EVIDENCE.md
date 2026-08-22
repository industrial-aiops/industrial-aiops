# 市场证据 — `docs/HLD.md` §11–12 的出处

> 核查日期 **2026-08-22**。本文件的作用是让 §11–12 的每一条判断**可被推翻**：
> 谁都可以顺着链接自己看一遍，而不是接受一段断言。
>
> ⚠️ **这些是二手公开资料，不是客户访谈。** 它们足以决定**先做什么**，
> **不足以**证明有人会买。真正的验证是 §5 那三个问题，问一个真客户。

## 1. 这个想法本身零差异化（HLD §11.1）

**闭环已是货架产品。** AspenTech 对 Aspen Mtell 的公开描述：分析 EAM 系统的工单 →
关联历史故障模式 → Software Agent 用工单信息生成**正常与故障的特征签名** →
部署后监测这些模式复现。

同层玩家：GE Digital APM、Augury、IBM Maximo APM。学术侧更进一步 ——
LLM + 领域知识图谱做 CNC 故障诊断（*Engineering*, 2025）。

- <https://www.aspentech.com/en/products/apm/aspen-mtell>
- <https://www.sciencedirect.com/science/article/pii/S2095809925001948>

**结论**：知识库不是护城河，也不是入口 —— 是留存机制。

## 2. PdM 的真实成功率（HLD §11.3）

- **60–70%** 的 PdM 项目卡在试点阶段（"pilot purgatory"）
- **75%** 的智能工厂项目走不出实验室
- 卡住的原因**不是算法**：几百台设备、跨厂、机型不同、维修历史不同、数据系统不同
- 成熟模型需**先积累足够历史**才达 85–95% 准确率，提前 2–6 周预警

- <https://www.iiot-world.com/predictive-analytics/predictive-maintenance/why-predictive-maintenance-stalls-after-first-win/>
- <https://www.criussoftware.com/blogsgrid.php?category=industrial-iot-architecture-scalable-data-platforms&slug=the-pilot-purgatory-survival-guide-why-smart-factory-initiatives-never-escape-the-lab>

**结论**：PdM 同时需要历史与标签，必须排最后。

## 3. OEE 的可量化痛点（HLD §11.2②）

> **手工 Excel 统计的 OEE 系统性高估 8–12 个百分点。**

原因：小停机（minor stoppage）**快到人根本记不下来**，纸面/表格记录对"六大损失"
里的小停机与降速**出了名的不准**。工厂看着自己 75%，实际可能 63%。

- <https://www.symestic.com/en-us/blog/oee/oee-benchmarks>
- <https://www.fabrico.io/blog/oee-data-collection-methods-guide/>

**结论**：这是**不需要任何反馈闭环**就能当场证明的差距 —— 接上 tap 即可。
也是 OEE 排第一的核心理由。

⚠️ **待核实**：8–12 这个区间来自行业博客对多份调研的转述（Evocon 2023、
Sage Clarity/Epicor 2021、SCW.ai 2022 等），**未见一手报告原文**。
用于对外材料前必须回溯到一手来源，否则标 `待核实`。

## 4. 「人会录入」是第一大失败模式（HLD §12.3）

- 大量 CMMS 项目失败，正是因为操作员和技师**根本不录**
- 要是报问题得登录系统、翻好几屏、填表，人就不用 —— 宁可口头告诉班长、发消息，
  或假定别人会处理
- **强制推行只会产出低质量数据**
- 工单故障码本身就不可靠：技师**随手点下拉框第一个**，于是满库
  「Fixed it」「Broken」「Miscellaneous」
- 工单是**为报账/合规**写的，不是为诊断写的

- <https://www.anymaint.com/post/the-cmms-adoption-gap>
- <https://f7i.ai/blog/work-order-accuracy-best-practices-transforming-maintenance-data-into-reliability-intelligence>
- <https://tractian.com/en/blog/data-quality-issues-that-cause-predictive-maintenance-challenges>

**结论**：`maintenance_log.py`（CMMS → 语料桥）喂进去的很可能是噪声。
标签必须来自**既有工作的副产品** —— 见 HLD §12.4（审计轨迹）。

## 5. 中小厂的可及性（HLD §11.6/§11.7）

- 预算是 **25%** 的中型厂列出的首要障碍，主因是 ROI 说不清
- 但成本正在塌陷：工业级振动/温度传感器**单价已低于 $1**
- 面向 SMB 的**交钥匙包**把实施复杂度降低 60–80%，多数小厂 2–4 周上线

- <https://f7i.ai/blog/how-to-evaluate-predictive-maintenance-providers-for-smb-manufacturing-a-2026-strategy-for-high-roi-reliability>
- <https://ifactoryapp.com/predictive-maintenance/overcoming-predictive-maintenance-implementation-challenges>

⚠️ **这条对我们不利，必须正视**：「中小厂被忽视」这个前提**正在失效**。
传感器加装派已经在积极下沉。

**但两条路线回答的不是同一个问题**：贴在电机上的振动传感器
**看不见**「上游缺料导致下游停机」—— 而这正是 OEE 损失待的地方。
详见 HLD §11.7。

## 6. OEE 是拥挤品类（HLD §11.6）

同场竞争者（部分）：Evocon、Fabrico、Symestic、TEEPTRAK、MaintMaster、
FactoryWiz、Excellerant，外加每一家 MES（Siemens Opcenter / Rockwell FactoryTalk /
AVEVA MES）。

**结论**：**不以「OEE 软件」入场**。差异在拿到数字的**路径**
（`scan` + `readiness` + 零加装硬件 + 一个下午），不在仪表盘 —— D27。

## 7. 该问客户的三个问题（唯一真正的验证）

上面全部是二手资料。按 `MEMORY` 里已定的判断（下一步是客户验证，不是继续建），
下列三问各自能证伪一条支柱：

| 问题 | 证伪什么 |
|---|---|
| **「你现在的 OEE 数字是怎么来的？」** | 若答 Excel → §3 的差距当场可验证；若答已有 MES 自动采集 → **OEE 入口这条路在这家厂不成立** |
| **「上次线停了 20 分钟，最后谁弄清楚为什么、花了多久？」** | 停机 RCA 的真实痛感。若答「没人查，重启就好了」→ RCA 的价值主张在这家厂是空的 |
| **「设备坏了之后，工单上的故障原因是谁填的、填得准吗？」** | 一个苦笑就说明**闭环这条路在这家厂走不通**，知识库要重新设计取标签的方式 |
