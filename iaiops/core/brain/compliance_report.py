"""合规报告渲染 — turn the compliance crosswalk into a CISO-readable document (A3).

Pure functions that render the existing ``iaiops.core.brain.compliance`` data
(CONTROLS / crosswalk / 等保 levels — reused, never duplicated) into a deliverable
等保 2.0 / IEC 62443 对照 report: Markdown by default, optional HTML via a small
stdlib converter (no jinja / docx dependency). The report is an honest onboarding
/ self-assessment aid, NOT a certification — the same disclaimer the tools carry.
"""

from __future__ import annotations

import html as _html

from iaiops import __version__ as _iaiops_version
from iaiops.core.brain.compliance import (
    compliance_dengbao_levels,
    compliance_frameworks,
    compliance_mapping,
)

DISCLAIMER = (
    "本报告为 onboarding / 自评参考 (self-assessment onboarding aid)，**非认证** "
    "(NOT a certification)。'待核实' = 已文档化但尚未验证 (documented, not yet "
    "validated)。逐项差距如实列出。"
)

_LEVEL_TITLES = {"l2": "第二级 (二级)", "l3": "第三级 (三级)", None: "二级 + 三级"}

# Governance mechanisms described in the appendix — config/code-sourced facts
# only (paths, commands, defaults), no marketing claims.
_GOVERNANCE_FACTS: tuple[tuple[str, str], ...] = (
    (
        "审计哈希链 (audit hash chain)",
        "每条审计记录写入 append-only SQLite (`~/.iaiops/audit.db`，可经 "
        "`IAIOPS_HOME` 重定位) 并携带 SHA-256 哈希链 (`prev_hash`/`row_hash`)；"
        "`iaiops audit verify` 逐行校验并报告第一处断链。局限：纯哈希链（无 HMAC "
        "密钥）可发现改写/删除，但不能对抗重写整段后缀的攻击者 — 建议配合 "
        "`iaiops audit forward` 将记录转发到外部 SIEM 留存异机副本。",
    ),
    (
        "审批令牌 (approval tokens / MOC)",
        "高危操作需要记录在案的审批人：`iaiops approve <tool> --endpoint <ep> "
        "--by <name>` 签发一次性、带 TTL 的审批令牌，由下一次匹配的受治理调用消费"
        '（审计行 `approver_source="token"`）；静态环境变量审批为已弃用的回退'
        '（`approver_source="env"`）。',
    ),
    (
        "dry-run / undo",
        "写/控制类工具默认 `dry_run=True`（预览、不执行），执行需 CLI 双重确认；"
        "任何写操作先捕获改前值 (BEFORE) 生成 undo 记录，可回滚。",
    ),
    (
        "mTLS / 加密凭据",
        "OPC-UA 证书安全模式 (Policy/Mode + 客户端证书/私钥，可选服务端证书校验) 与 "
        "MQTT TLS (CA + 客户端证书双向认证) 均从配置的证书路径装配（配置中只存路径，"
        "不存密钥材料）；凭据存于加密 secret store (Fernet + scrypt，"
        "`~/.iaiops/secrets.enc`)，不落日志。",
    ),
)


def _cell(text: str) -> str:
    """Escape a value for use inside a Markdown table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    """Render a Markdown table as a list of lines."""
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    return lines


def render_markdown_report(
    *,
    site: str = "",
    date: str = "",
    level: str | None = None,
    version: str = _iaiops_version,
) -> str:
    """Render the full compliance report as Markdown.

    Args:
        site: Site / plant name for the title page (free text).
        date: Report date (caller-supplied, e.g. ISO ``2026-07-02``).
        level: 等保 level focus — 'l2'/'l3'/二级/三级; None renders both.
        version: iaiops version stamped on the title page.

    Raises:
        ValueError: on an unrecognized 等保 level (via compliance_dengbao_levels).
    """
    dengbao = compliance_dengbao_levels(level)  # validates + normalizes level
    selected: str | None = dengbao["selected_level"]
    mapping = compliance_mapping()
    frameworks = compliance_frameworks()

    lines: list[str] = [
        "# 工控网络安全合规自评报告 (iaiops compliance self-assessment)",
        "",
        f"- **现场 / Site**: {site or '（未指定）'}",
        f"- **报告日期 / Date**: {date or '（未指定）'}",
        f"- **iaiops 版本**: {version}",
        f"- **等保 2.0 目标等级**: {_LEVEL_TITLES[selected]}",
        f"- **对照框架**: {' / '.join(f['name'] for f in frameworks['frameworks'])}",
        "",
        f"> {DISCLAIMER}",
        "",
        "## 1. 总览 (executive summary)",
        "",
    ]
    summary = mapping["status_summary"]
    lines.extend(
        _table(
            ("控制项总数", "addressed", "partial", "待核实"),
            [
                (
                    str(mapping["control_count"]),
                    str(summary["addressed"]),
                    str(summary["partial"]),
                    str(summary["待核实"]),
                )
            ],
        )
    )

    lines.extend(
        [
            "",
            f"## 2. 等保 2.0 (GB/T 22239-2019) — {_LEVEL_TITLES[selected]} 逐支柱状态",
            "",
        ]
    )
    headers: tuple[str, ...] = ("支柱 (pillar)",)
    if selected in (None, "l2"):
        headers += ("二级基线 (L2)",)
    if selected in (None, "l3"):
        headers += ("三级增量 (L3 adds)",)
    headers += ("iaiops 姿态", "状态")
    rows: list[tuple[str, ...]] = []
    for delta in dengbao["deltas"]:
        row: tuple[str, ...] = (delta["pillar"],)
        if selected in (None, "l2"):
            row += (delta.get("l2_requires", ""),)
        if selected in (None, "l3"):
            row += (delta.get("l3_adds", ""),)
        row += (delta["iaiops"], delta["iaiops_status"])
        rows.append(row)
    lines.extend(_table(headers, rows))

    lines.extend(["", "## 3. IEC 62443 FR1–FR6 跨框架对照 (crosswalk)", ""])
    lines.extend(
        _table(
            ("支柱 (pillar)", "等保 2.0 条款", "IEC 62443 FR", "状态"),
            [
                (r["pillar"], r["dengbao"], r["iec62443"], r["iaiops_status"])
                for r in frameworks["crosswalk"]
            ],
        )
    )

    lines.extend(["", "## 4. 差距清单 (honest gap list)", ""])
    gaps = [c for c in mapping["controls"] if c.get("gap")]
    if gaps:
        lines.extend(
            f"- **{c['pillar']}** [{c['status']}] — {' '.join(str(c['gap']).split())}" for c in gaps
        )
    else:
        lines.append("- （无已知差距 — 见各支柱状态）")

    lines.extend(
        [
            "",
            "## 附录 A. 治理机制 (governance controls)",
            "",
            "以下为 iaiops 治理骨架的事实性描述（来源：代码/配置，非营销口径）：",
            "",
        ]
    )
    for name, fact in _GOVERNANCE_FACTS:
        lines.extend([f"### {name}", "", fact, ""])

    lines.extend(
        [
            "## 附录 B. 各支柱实现细节 (per-pillar detail)",
            "",
        ]
    )
    for control in mapping["controls"]:
        lines.extend(
            [
                f"### {control['pillar']} — {control['status']}",
                "",
                f"- **要求**: {_cell(control['requirement'])}",
                f"- **iaiops**: {_cell(control['iaiops'])}",
                f"- **差距**: {_cell(control['gap']) or '无'}",
                "",
            ]
        )

    lines.extend(["---", "", f"> {DISCLAIMER}", ""])
    return "\n".join(lines)


# ── Minimal stdlib Markdown → HTML (headings / tables / lists / quotes) ──────


def _inline_html(text: str) -> str:
    """Escape text and convert **bold** / `code` spans."""
    escaped = _html.escape(text, quote=False)
    for marker, tag in (("**", "strong"), ("`", "code")):
        parts = escaped.split(marker)
        if len(parts) >= 3:
            out: list[str] = [parts[0]]
            for i, part in enumerate(parts[1:], start=1):
                out.append(f"<{tag}>" if i % 2 == 1 else f"</{tag}>")
                out.append(part)
            if len(parts) % 2 == 0:  # unbalanced marker — close the tag
                out.append(f"</{tag}>")
            escaped = "".join(out)
    return escaped


def _flush_table(buffer: list[str], out: list[str]) -> None:
    if not buffer:
        return
    out.append("<table>")
    for i, line in enumerate(buffer):
        if i == 1:
            continue  # the |---| separator row
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        tag = "th" if i == 0 else "td"
        out.append(
            "<tr>"
            + "".join(
                f"<{tag}>{_inline_html(c.replace(chr(92) + '|', '|'))}</{tag}>" for c in cells
            )
            + "</tr>"
        )
    out.append("</table>")
    buffer.clear()


_HTML_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;"
    "padding:0 1rem;line-height:1.6}table{border-collapse:collapse;width:100%;"
    "margin:1rem 0}th,td{border:1px solid #999;padding:.4rem .6rem;text-align:left;"
    "vertical-align:top}th{background:#f0f0f0}blockquote{border-left:4px solid "
    "#c60;background:#fff8f0;margin:1rem 0;padding:.5rem 1rem}"
)


def render_html_report(
    *,
    site: str = "",
    date: str = "",
    level: str | None = None,
    version: str = _iaiops_version,
) -> str:
    """Render the compliance report as a standalone HTML page (stdlib only)."""
    markdown = render_markdown_report(site=site, date=date, level=level, version=version)
    body: list[str] = []
    table_buffer: list[str] = []
    in_list = False
    for line in markdown.split("\n"):
        if line.startswith("|"):
            table_buffer.append(line)
            continue
        _flush_table(table_buffer, body)
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline_html(line[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if line.startswith("#"):
            depth = len(line) - len(line.lstrip("#"))
            body.append(f"<h{depth}>{_inline_html(line[depth:].strip())}</h{depth}>")
        elif line.startswith("> "):
            body.append(f"<blockquote>{_inline_html(line[2:])}</blockquote>")
        elif line.strip() == "---":
            body.append("<hr>")
        elif line.strip():
            body.append(f"<p>{_inline_html(line)}</p>")
    _flush_table(table_buffer, body)
    if in_list:
        body.append("</ul>")
    title = _html.escape("iaiops 合规自评报告" + (f" — {site}" if site else ""))
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n<style>{_HTML_STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


__all__ = ["render_markdown_report", "render_html_report", "DISCLAIMER"]
