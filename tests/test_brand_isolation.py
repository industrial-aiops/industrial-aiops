"""The brand-isolation gate CLAUDE.md said existed.

`CLAUDE.md` lists five 「质量门(发布前全绿)」. Four are enforced — pytest, ruff,
bandit, and the every-tool-is-governed check. The fifth, 「零跨品牌禁用词」, was
enforced by **convention only**: a pre-release audit on 2026-08-25 searched
`tests/`, `scripts/` and `.github/workflows/` and found no implementation.

The repo happened to be clean, which is the dangerous shape — a rule everybody
believes is mechanical, that nothing checks. This repo's own iron rule is that it
must not claim a capability it does not have; a claimed gate is a capability.

**Why the rule exists.** `industrial-aiops` is a separate org from the IT line and
unrelated to any hypervisor/backup vendor. An IT product name in an OT repo is not
a typo — it is the wrong product leaking into the wrong market, in a file a
customer or an auditor reads.

**Why an allowlist is necessary rather than a weakening.** Two of the five hits a
naive grep finds are *negative routing rules* — "Do NOT use for … Kubernetes,
hypervisors, or backups" — which exist to keep this tool from being dispatched to
IT work. Deleting the word to satisfy the grep would weaken the very isolation the
rule protects. Two more are a vendored upstream schema that must stay byte-exact,
and one is a citation URL frozen in published changelog history.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent

#: IT product names that must not appear in an OT repo. Deliberately narrow —
#: product names, not generic words, so the gate is about brand leakage and not
#: about vocabulary.
FORBIDDEN = (
    "vmware",
    "vsphere",
    "vsan",
    "nsx",
    "esxi",
    "vcenter",
    "broadcom",
    "proxmox",
    "veeam",
    "kubernetes",
    "k8s",
    "openshift",
    "hyper-v",
)

#: Paths whose content is not ours to edit, or where the word is load-bearing.
#: Each entry states WHY, because an allowlist without reasons becomes the place
#: violations go to hide.
ALLOWED: dict[str, str] = {
    # Vendored verbatim from upstream Margo at a recorded commit; PROVENANCE.md
    # documents it as an unmodified copy and an offline schema gate checks it.
    "deploy/margo/schema": "vendored upstream schema — must stay byte-exact",
    # Negative routing rules. The word is what stops an OT skill being dispatched
    # to IT work; removing it weakens the isolation this gate protects.
    "skills/iaiops/SKILL.md": "negative routing rule — scopes the skill AWAY from IT",
    "mcp_server/_shared.py": "negative routing rule — scopes the tool surface AWAY from IT",
    # Published release history. Rewriting it to hide where a field report came
    # from would be worse than the hit.
    "CHANGELOG.md": "frozen release history — a citation URL in a shipped entry",
    # This file names them in order to forbid them.
    "tests/test_brand_isolation.py": "the gate itself",
}

#: Directories that are not source.
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "node_modules",
    ".claude",
}

#: Extensions worth scanning. Binary and lock files are excluded.
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".sh", ".txt", ".cfg", ".ini"}


def _allowed(rel: str) -> str | None:
    for prefix, why in ALLOWED.items():
        if rel == prefix or rel.startswith(prefix + "/"):
            return why
    return None


def _scan() -> list[tuple[str, int, str, str]]:
    """Every forbidden word outside the allowlist, as (path, line, word, text)."""
    pattern = re.compile("|".join(re.escape(w) for w in FORBIDDEN), re.IGNORECASE)
    hits: list[tuple[str, int, str, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(ROOT))
        if _allowed(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            found = pattern.search(line)
            if found:
                hits.append((rel, number, found.group(0), line.strip()[:120]))
    return hits


class TestNoITBrandLeaksIntoTheOTRepo:
    def test_the_tree_is_clean(self):
        hits = _scan()
        assert not hits, "IT product names in an OT repo:\n" + "\n".join(
            f"  {p}:{n}  {w!r}  {t}" for p, n, w, t in hits
        )

    def test_the_gate_can_actually_see_a_violation(self):
        """A gate nobody has watched fail is a gate nobody knows works — and this
        one spent its whole life unimplemented while being listed as enforced."""
        probe = ROOT / "tests" / "_brand_probe_tmp.md"
        probe.write_text("this file mentions VMware vSphere\n", encoding="utf-8")
        try:
            hits = _scan()
            assert any(p.endswith("_brand_probe_tmp.md") for p, _, _, _ in hits)
        finally:
            probe.unlink(missing_ok=True)

    def test_every_allowlist_entry_still_exists(self):
        """An allowlist entry for a deleted path is a hole waiting for a new file
        to be created at that name."""
        for rel in ALLOWED:
            assert (ROOT / rel).exists(), f"allowlisted path no longer exists: {rel}"

    def test_every_allowlist_entry_states_why(self):
        for rel, why in ALLOWED.items():
            assert why and len(why) > 10, f"{rel} is allowlisted without a reason"
