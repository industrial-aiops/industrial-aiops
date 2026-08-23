"""Persistence for a site's knowledge base — owner-only JSON, never a device write.

Follows the ``alias_store`` conventions exactly rather than inventing a second
scheme: one JSON file per site under the iaiops home, 0600, written atomically
(temp file + replace), sorted keys so a diff is readable and a human can inspect
what the tool believes about their plant.

Readability is deliberate. This file is the accumulated opinion of a tool about
someone's factory; if they cannot open it and see that a relationship is marked
``suggested`` rather than ``declared``, the provenance guarantee only exists
inside the process that wrote it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from iaiops.core.knowledge.model import KnowledgeBase

SUBDIR = "knowledge"
_SAFE_SITE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _safe_site(site: str) -> str:
    """Reject anything that could escape the knowledge directory."""
    name = str(site or "").strip()
    if not _SAFE_SITE.match(name):
        raise ValueError(
            f"Site name {site!r} must be 1-64 chars of letters, digits, dot, dash "
            "or underscore — it becomes a filename."
        )
    return name


def site_path(site: str, base_dir: Path | None = None) -> Path:
    from iaiops.core.runtime.config import CONFIG_DIR

    root = Path(base_dir) if base_dir else CONFIG_DIR
    return root / SUBDIR / f"{_safe_site(site)}.json"


def save(kb: KnowledgeBase, base_dir: Path | None = None) -> Path:
    """Persist ``kb``; returns the path written."""
    path = site_path(kb.site, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(kb.as_dict(), indent=2, sort_keys=True, ensure_ascii=False), "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    return path


def load(site: str, base_dir: Path | None = None) -> KnowledgeBase:
    """Load a site's base. A site with none yet gets an EMPTY base, not an error.

    That distinction carries the D20 rule into the code: the product has to work
    on a site that has accumulated nothing, so "no knowledge yet" is an ordinary
    starting state rather than a fault to report.
    """
    path = site_path(site, base_dir)
    if not path.exists():
        return KnowledgeBase(site=_safe_site(site))
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Knowledge base for {site!r} at {path} is unreadable: {exc}") from exc
    return KnowledgeBase.from_dict(raw)


__all__ = ["save", "load", "site_path", "SUBDIR"]
