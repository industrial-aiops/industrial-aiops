"""Refresh a bounded contribution registry using read-only GitHub API calls."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/community"


def api(endpoint):
    result = subprocess.run(
        ["gh", "api", endpoint], capture_output=True, text=True, check=True, timeout=40
    )
    return json.loads(result.stdout)


def refresh(record):
    repo = record["repo"]
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Invalid repository")
    number = int(record["number"])
    kind = record["kind"]
    if kind == "pr":
        data = api(f"repos/{repo}/pulls/{number}")
        state = (
            "merged"
            if data["merged_at"]
            else "closed_unmerged"
            if data["state"] == "closed"
            else "draft"
            if data["draft"]
            else "open"
        )
    elif kind == "issue":
        data = api(f"repos/{repo}/issues/{number}")
        state = data["state"]
    elif kind == "comment":
        data = api(f"repos/{repo}/issues/comments/{int(record['comment_id'])}")
        parent = api(f"repos/{repo}/issues/{number}")
        state = "posted; parent " + parent["state"]
    else:
        raise ValueError("Unsupported kind")
    if record["role"] == "author" or kind == "comment":
        if data["user"]["login"] != "zw008":
            raise ValueError(f"Unexpected author at {repo}#{number}")
    result = {
        **record,
        "status": state,
        "url": data["html_url"],
        "actual_author": data["user"]["login"],
        "updated_at": data["updated_at"],
        "merged_at": data.get("merged_at"),
        "comments": data.get("comments"),
        "head_sha": data.get("head", {}).get("sha"),
    }
    if kind == "issue" and record["role"] == "commenter":
        comments = api(f"repos/{repo}/issues/{number}/comments?per_page=100")
        own = [c["html_url"] for c in comments if c["user"]["login"] == "zw008"]
        if not own:
            raise ValueError(
                f"No account participation verified in first 100 comments: {repo}#{number}"
            )
        result["participation_urls"] = own
    return result


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(snapshot):
    lines = [
        "# 社区贡献与 PR 跟踪台账",
        "",
        f"最后核对：{snapshot['checked_at_shanghai']}（Asia/Shanghai）。",
        "",
        "只读 GitHub API 快照；不是实时状态，也不是账号全部活动清单。",
        "合并按 merged_at 判断，closed 不自动算合并；自身 PR、他人承接 PR、",
        "上游 issue/comment 与未外投草稿分开记录。没有把已提交等同于社区认可或认证。",
        "",
        "重要更正：zw008 已有 Tahu #472、Margo CTT #16/#20 等外部提交。",
        "此前本聊天中“尚未向外部提交”的概括不完整，应以本台账核对结果为准。",
        "",
    ]
    for heading, predicate in [
        (
            "本人提交的上游 PR",
            lambda r: (
                r["kind"] == "pr"
                and r["role"] == "author"
                and not r["repo"].startswith("industrial-aiops/")
            ),
        ),
        ("相关承接 PR（不是本人提交）", lambda r: r["role"] == "related"),
        ("上游 issue 与讨论参与", lambda r: r["kind"] in {"issue", "comment"}),
        ("自身仓库 PR（不计为外部贡献）", lambda r: r["repo"].startswith("industrial-aiops/")),
    ]:
        lines += [
            f"## {heading}",
            "",
            "| 项目与记录 | 内容 | 当前状态 | 参与身份 | 下一步 |",
            "|---|---|---|---|---|",
        ]
        for r in snapshot["records"]:
            if predicate(r):
                label = f"{r['repo']} #{r['number']}" + (
                    " comment" if r["kind"] == "comment" else ""
                )
                lines.append(
                    f"| [{label}]({r['url']}) | {cell(r['summary'])} | {cell(r['status'])} | "
                    f"{cell(r['role'])}; GitHub 作者 {cell(r['actual_author'])} | "
                    f"{cell(r['next_action'])} |"
                )
        lines += [""]
    lines += [
        "## 未提交的外部草稿与候选",
        "",
        "| 项目 | 内容 | 状态 | 下一步 |",
        "|---|---|---|---|",
    ]
    for d in snapshot["drafts"]:
        label = f"[{d['project']}]({d['artifact']})" if d.get("artifact") else d["project"]
        lines.append(
            f"| {label} | {cell(d['summary'])} | {d['status']} | {cell(d['next_action'])} |"
        )
    lines += [
        "",
        "## 每次日常维护的跟踪顺序",
        "",
        "1. 刷新状态，查看更新日期、review、CI 和维护者回复；避免重复提交。",
        "2. 按待办重跑固定版本实验，记录命令、提交、证据和未验证边界。",
        "3. 回应或修改前先准备可审阅结果；对外消息、PR、注册另行明确执行。",
        "4. 合并后检查目标分支/发布版本是否包含变更，最后才更新本地验证结论。",
        "",
        "刷新命令（需要 gh 已认证；只 GET，不提交或发送消息）：",
        "",
        "```bash",
        "python3 scripts/community/refresh_contribution_tracker.py --write",
        "```",
        "",
        "不加 --write 只输出 JSON 到标准输出。任何查询失败都不覆盖已有快照。",
        "维护 contribution-registry.json 中的内容与下一步；状态保存在 contribution-snapshot.json。",
        "新增参与记录应登记真实 URL；刷新不代替全账号活动发现，也不自动安排定时任务。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    registry = json.loads((DIRECTORY / "contribution-registry.json").read_text())
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(refresh, registry["records"]))
    now = datetime.now(UTC)
    snapshot = {
        **registry,
        "checked_at_utc": now.isoformat(),
        "checked_at_shanghai": now.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "records": records,
    }
    output = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if args.write:
        (DIRECTORY / "contribution-snapshot.json").write_text(output)
        (ROOT / "docs/COMMUNITY-CONTRIBUTIONS.md").write_text(render(snapshot))
        print(f"Refreshed {len(records)} records; no upstream mutations")
    else:
        print(output)


if __name__ == "__main__":
    main()
