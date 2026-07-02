# 信创 / China-entry guide (offline install · 国产 OS·芯·PLC · 合规)

> Onboarding guide for 自主可控 / 信创 deployments (e.g. fabs like 华星). Covers
> air-gapped install, 国产 OS/芯/PLC validation, the national-TSDB historian sink,
> and the compliance mapping. **Status is honest**: items marked `待核实` are
> designed/documented but **not yet hardware-verified** — this is a preview line.

## 1. 定位

iaiops is a **read-first, governed OT data tap** — exactly the posture 工控安全
guidance wants: minimal capability, auditable, change-gated. For China deployments
the differentiators are: **no mandatory public-internet dependency**, **domestic
TSDB sinks** (TDengine / IoTDB) instead of InfluxDB, **国产 PLC over the existing
Modbus/Ethernet paths**, and a **built-in compliance self-assessment**
(`iaiops compliance` / the `compliance_mapping` MCP tool).

## 2. 离线 / 气隙安装 (air-gapped)

The package is pure-Python at its core; each protocol is an **optional extra**, so
an air-gapped host installs only what it needs from a **local wheelhouse** — no
public index access at install time.

```bash
# On an internet-connected build host (same OS/arch/Python as the target):
pip download "iaiops[modbus,opcua]" -d ./wheelhouse        # add the extras you need
#   …for 信创 sinks:  pip download "iaiops[tdengine,iotdb]" -d ./wheelhouse

# Move ./wheelhouse to the air-gapped host (USB / approved transfer), then:
pip install --no-index --find-links ./wheelhouse "iaiops[modbus,opcua]"
```

Notes:
- Build the wheelhouse on a host matching the target **OS + CPU arch + Python
  minor version** (native wheels — e.g. `pysoem`, `c104`, `pydnp3` — are not
  cross-platform). For 国产 OS/芯 targets, build on that same 麒麟/统信 + 鲲鹏/海光
  host. `待核实`.
- The base install + the pure-Python connectors (modbus, s7 `pyS7`, mc, eip,
  sparkplug, mqtt) need no native toolchain. `iec61850` needs **libiec61850**
  built on the target; `pydnp3` / `pysoem` / `c104` build native extensions.
- Secrets stay local in the encrypted store (`~/.iaiops/secrets.enc`); no cloud
  KMS dependency. Set `IAIOPS_AIOPS_MASTER_PASSWORD` for non-interactive/MCP use.

## 3. 国产 OS / 芯 / PLC 验证矩阵 (待核实)

> **None of the rows below are hardware-verified yet** — this is the plan + the
> expected path. Update each cell to ✅ + a version as it is validated.

| 维度 | 目标 | 预期路径 | 状态 |
|------|------|----------|:----:|
| 国产 OS | 麒麟 (Kylin) V10 · 统信 UOS | Python ≥3.11 venv; build native extras on-target | 待核实 |
| 国产 芯 | 鲲鹏 (aarch64) · 海光 (x86_64) | wheelhouse built per-arch; pure-Python core is arch-agnostic | 待核实 |
| 国产 PLC | 汇川 (Inovance) · 台达 (Delta) · 信捷 (Xinje) | over the **existing Modbus-TCP / Ethernet** connector (`protocol: modbus`) | 待核实 |
| 替换性 | declare replaceable overseas deps | per-protocol extras isolate each library; sinks use domestic TDengine/IoTDB | partial |

国产 PLC 多以 **Modbus-TCP** 暴露数据 — 直接用现有 `modbus` connector + `iaiops
doctor` 验证链路；S7-兼容的国产 PLC 走 `s7` connector（`pyS7` 纯 Python）。

## 4. 国产时序库 historian sink (TDengine / IoTDB)

Push **already-collected** telemetry into a domestic TSDB — *data egress to the
operator's own historian*, never a control-system write (low-risk, governed).

```bash
pip install "iaiops[tdengine]"        # or iaiops[iotdb], or iaiops[xinchuang] for both

# CLI: write a JSON list of points (e.g. from `iaiops modbus read-holding`)
iaiops historian push --sink tdengine --input points.json \
  --host 10.0.0.20 --database iaiops
```

Or via the `historian_push` MCP tool (`sink="tdengine"|"iotdb"`). Points are
normalized from any connector's output (`{ref|metric, value|present_value,
timestamp?}`); non-numeric points are skipped (these TSDBs store a numeric value
column). **✅ Live-verified 2026-06-30** (write→read round-trip against
containerized servers): IoTDB via the real `IoTDBSink`; TDengine after fixing a
real DDL bug (the `value` column is a TDengine reserved word — back-quoted in
`CREATE STABLE`). Production cluster scale/HA/auth tuning remains site-specific.

Design choice: we **do not build our own historian** and **do not bind InfluxDB** —
the sink is a thin adapter so a site uses its existing domestic TSDB.

## 5. 合规映射 — 《工控系统网络安全防护指南》 / 等保 2.0 / IEC 62443

`iaiops compliance` (or the `compliance_mapping` MCP tool) prints an honest
mapping of the iaiops governance posture to the guidance pillars:

| 支柱 | iaiops 如何满足 | 状态 |
|------|------------------|:----:|
| 分区隔离 | read-first 单一用途；`IAIOPS_MCP` 按区暴露协议；不跨端点桥接 | addressed |
| 可审计 | 全工具经治理 harness：审计库 `~/.iaiops/audit.db` + 预算熔断 + undo 记录 | addressed |
| 双向认证 | OPC-UA 用户名/密码、MQTT TLS+凭据、加密 secret 库 | partial (mTLS 待核实) |
| 最小权限 | 读优先；写=HIGH risk_tier、dry-run、双确认+MOC+undo | addressed |
| 数据保护 | Fernet 加密 secret 库；配置目录权限告警；secret 不记录 | addressed |
| 自主可控 | 纯 Python 核心、可选 extras、离线安装、国产 TSDB sink、国产 PLC over Modbus | 待核实 |

> This is an **onboarding/sales self-assessment, not a certification**. The
> `待核实` rows are the validation backlog for a China deployment engagement.

### 5.1 跨框架对照 (等保 2.0 / IEC 62443)

`compliance_frameworks` (MCP tool) 把同一治理支柱同时对到 **等保 2.0
(GB/T 22239-2019)** 的控制类与 **IEC 62443** 的基础需求 (FR)，回答“这条满足哪条
等保 / 62443 条款”：

| 支柱 | 等保 2.0 控制类 | IEC 62443 基础需求 |
|------|------------------|---------------------|
| 分区隔离 | 安全通信网络·网络架构 / 安全区域边界 | FR5 受限数据流 (RDF) — zones & conduits |
| 可审计 | 安全计算环境·安全审计 + 安全管理中心·集中管控 | FR6 事件及时响应 (TRE) — SR 2.8–2.12 |
| 双向认证 | 安全计算环境·身份鉴别 / 通信传输加密 | FR1 标识与鉴别控制 (IAC) — SR 1.1–1.9 |
| 最小权限 | 安全计算环境·访问控制 (最小权限) | FR2 使用控制 (UC) — SR 2.1 |
| 数据保护 | 安全计算环境·数据保密性/完整性 | FR4 数据保密性 (DC) — SR 4.1–4.3 |
| 自主可控 | 安全建设管理·产品采购和使用 | FR3 系统完整性 + IEC 62443-4-1 |

> 对照为 onboarding/审计参考、非认证映射。逐项 gap 与状态仍以 `compliance_mapping`
> 为准（每条 control 现也内嵌 `crosswalk` 字段）。

## 6. 验证债 (open items)

- 国产 OS/芯/PLC：上述矩阵全部 `待核实` — 需在 麒麟/统信 + 鲲鹏/海光 + 汇川/台达/信捷
  上实测并回填版本。
- ~~TSDB sink：写路径未对真实集群验证~~ → **✅ 已验证 (2026-06-30)**：IoTDB / TDengine
  容器写读 round-trip 通过(TDengine 修了 `value` 保留字 DDL bug)。生产集群规模/HA 仍按现场调优。
- mTLS / 证书双向认证：OPC-UA cert 安全模式、MQTT 客户端证书为 roadmap。
- 审计外发到集中 SIEM：当前需自行导出/转发审计库。
