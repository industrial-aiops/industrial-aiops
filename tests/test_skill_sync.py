"""SKILL.md ↔ MCP tool-registry sync guard.

Every ``@mcp.tool``-registered function in ``mcp_server/tools/*.py`` must be
documented in ``skills/iaiops/SKILL.md`` (as `backticked_name`) so the skill
never drifts behind the actual tool surface again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "mcp_server" / "tools"
SKILL_FILE = REPO_ROOT / "skills" / "iaiops" / "SKILL.md"

# @mcp.tool() possibly followed by more decorators, then the def line.
_TOOL_DEF_RE = re.compile(r"@mcp\.tool\(\)(?:\n@[^\n]+)*\ndef ([A-Za-z_][A-Za-z0-9_]*)")


def _registered_tool_names() -> list[str]:
    names: list[str] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        names.extend(_TOOL_DEF_RE.findall(path.read_text("utf-8")))
    return names


@pytest.mark.unit
def test_registry_is_nonempty_sanity():
    names = _registered_tool_names()
    assert len(names) >= 100, f"suspiciously few tools parsed: {len(names)}"


@pytest.mark.unit
def test_every_registered_tool_documented_in_skill():
    skill = SKILL_FILE.read_text("utf-8")
    missing = [n for n in _registered_tool_names() if f"`{n}`" not in skill]
    assert not missing, (
        f"SKILL.md is missing {len(missing)} registered tool(s): {missing}. "
        f"Add a one-line entry for each to {SKILL_FILE}."
    )


@pytest.mark.unit
def test_skill_write_tool_count_matches_registry():
    """The 'N write tools' claims in SKILL.md must match the high-risk registry."""
    high_risk: list[str] = []
    pattern = re.compile(
        r'@mcp\.tool\(\)\n@governed_tool\(risk_level="high"[^)]*\)(?:\n@[^\n]+)*\ndef (\w+)'
    )
    for path in sorted(TOOLS_DIR.glob("*.py")):
        high_risk.extend(pattern.findall(path.read_text("utf-8")))
    skill = SKILL_FILE.read_text("utf-8")
    claims = re.findall(r"The (\d+) write tools", skill)
    assert claims, "SKILL.md no longer states the write-tool count"
    for claim in claims:
        assert int(claim) == len(high_risk), (
            f"SKILL.md claims {claim} write tools but the registry has "
            f"{len(high_risk)}: {sorted(high_risk)}"
        )
