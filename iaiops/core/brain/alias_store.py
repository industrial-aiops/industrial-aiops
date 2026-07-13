"""Adopted alias-map persistence + cross-run diff (pure logic + bounded file I/O).

The tag-discovery / cross-protocol asset model (:mod:`iaiops.core.brain.asset_model`)
*proposes* canonical aliases, but a proposal nobody records drifts silently. This
module closes that loop:

  * :func:`extract_alias_map` turns an asset-model run into a compact ADOPTED map
    ``{canonical_alias: {ref, protocol, asset, name, class}}``;
  * :func:`save_alias_map` / :func:`load_alias_map` persist that baseline per site
    under the iaiops config dir (``<home>/aliases/<site>.json``, owner-only perms);
  * :func:`diff_alias_map` compares a stored baseline against a fresh run and
    reports **added / removed / renamed / reclassified** tags + a stable/changed
    verdict — so an operator sees how the address space moved between runs.

Everything is pure except the small, validated save/load boundary (which steers
all I/O through the harness home and never writes plaintext secrets). It is
advisory: the map is a SUGGESTION an operator adopts, never a server-side rename.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from iaiops.core.governance.paths import ops_home

ALIASES_SUBDIR = "aliases"
_FORMAT_VERSION = 1
# A site label is a filesystem leaf — keep it to safe chars (no path traversal).
_SAFE_SITE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# Fields kept per adopted tag (the stable identity + the human-facing labels).
_ENTRY_FIELDS = ("ref", "protocol", "asset", "name", "class")


# ── extraction from an asset-model run ─────────────────────────────────────────


def extract_alias_map(model: Any) -> dict[str, dict[str, str]]:
    """Build an adopted alias map from a ``cross_protocol_asset_model`` result.

    Returns ``{canonical_alias: {ref, protocol, asset, name, class}}`` — a fresh
    dict; the input model is never mutated. Raises a teaching ``ValueError`` if
    ``model`` is not an asset-model shape.
    """
    if not isinstance(model, dict) or not isinstance(model.get("assets"), list):
        raise ValueError(
            "extract_alias_map expects a cross-protocol asset model "
            "(a dict with an 'assets' list, as returned by "
            "cross_protocol_asset_model); got "
            f"{type(model).__name__}."
        )
    out: dict[str, dict[str, str]] = {}
    for asset in model["assets"]:
        for tag in asset.get("tags") or []:
            alias = str(tag.get("canonical_alias") or "")
            if not alias or alias in out:
                continue
            out[alias] = {
                "ref": str(tag.get("ref") or ""),
                "protocol": str(tag.get("protocol") or ""),
                "asset": str(tag.get("asset") or ""),
                "name": str(tag.get("name") or ""),
                "class": str(tag.get("klass") or tag.get("class") or "other"),
            }
    return out


# ── persistence ────────────────────────────────────────────────────────────────


def _safe_site(site: Any) -> str:
    """Validate a site label as a safe filesystem leaf (no traversal)."""
    label = str(site or "").strip().lower()
    if not _SAFE_SITE.match(label):
        raise ValueError(
            f"Invalid site '{site}'. A site label must be alphanumeric and may "
            "contain '_' or '-' (no spaces, dots, or path separators) so it is a "
            "safe file name — e.g. 'plant', 'line1', 'fab-a'."
        )
    return label


def _aliases_root(base_dir: Path | None) -> Path:
    """Resolve the directory holding per-site adopted alias maps."""
    base = Path(base_dir) if base_dir is not None else ops_home()
    return base / ALIASES_SUBDIR


def _site_path(site: Any, base_dir: Path | None) -> Path:
    """Resolve the JSON file for a site's adopted alias map."""
    return _aliases_root(base_dir) / f"{_safe_site(site)}.json"


def _ensure_dir(directory: Path) -> None:
    """Create the aliases dir with owner-only (0700) perms (best effort)."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:  # best effort on exotic filesystems
        pass


def _validate_map(alias_map: Any, label: str) -> dict[str, dict]:
    """Validate that ``alias_map`` is a ``{alias: {...}}`` dict (boundary check)."""
    if not isinstance(alias_map, dict):
        raise ValueError(
            f"{label} must be an alias map (a dict of "
            "{canonical_alias: {ref, protocol, asset, name, class}}), got "
            f"{type(alias_map).__name__}."
        )
    for alias, entry in alias_map.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"{label} entry for alias '{alias}' must be an object, got {type(entry).__name__}."
            )
    return alias_map


def _normalized_entries(alias_map: dict[str, dict]) -> dict[str, dict[str, str]]:
    """Return a fresh, field-bounded copy of the map (deterministic on disk)."""
    out: dict[str, dict[str, str]] = {}
    for alias in sorted(alias_map):
        entry = alias_map[alias]
        out[alias] = {f: str(entry.get(f) or "") for f in _ENTRY_FIELDS}
    return out


def save_alias_map(site: str, alias_map: Any, *, base_dir: Path | None = None) -> Path:
    """Persist an adopted alias map for ``site`` (owner-only JSON). Returns the path.

    Validates the inputs at the boundary and writes atomically (temp file +
    replace) with 0600 perms under ``<home>/aliases/``. The on-disk ``aliases``
    block is sorted for a deterministic, diff-friendly file.
    """
    safe = _safe_site(site)
    _validate_map(alias_map, "save_alias_map")
    payload = {
        "version": _FORMAT_VERSION,
        "site": safe,
        "aliases": _normalized_entries(alias_map),
    }
    path = _site_path(safe, base_dir)
    _ensure_dir(path.parent)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    return path


def load_alias_map(site: str, *, base_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """Load a previously adopted alias map for ``site``.

    Raises ``FileNotFoundError`` (teaching) when no baseline exists, or
    ``ValueError`` when the file is corrupt / not the expected shape.
    """
    path = _site_path(site, base_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"No adopted alias map for site '{site}'. Adopt one first "
            "(iaiops analytics alias-adopt --input feeds.json --site "
            f"{_safe_site(site)})."
        )
    try:
        payload = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Adopted alias map for site '{site}' is not valid JSON ({e}). "
            "Re-adopt it with 'iaiops analytics alias-adopt'."
        ) from e
    if not isinstance(payload, dict) or not isinstance(payload.get("aliases"), dict):
        raise ValueError(
            f"Adopted alias map for site '{site}' is malformed (missing an "
            "'aliases' object). Re-adopt it with 'iaiops analytics alias-adopt'."
        )
    return _validate_map(payload["aliases"], "loaded alias map")


def list_sites(*, base_dir: Path | None = None) -> list[str]:
    """List the sites that have an adopted alias map (sorted), or ``[]`` if none."""
    root = _aliases_root(base_dir)
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.json") if p.is_file())


# ── cross-run diff ─────────────────────────────────────────────────────────────


def _identity(alias: str, entry: dict) -> tuple[str, str, str]:
    """Stable identity of a tag: its (protocol, ref) when it has a ref, else alias.

    ``ref`` (node id / register address) is the physical handle that survives a
    rename; tags with no ref can only be tracked by their alias (so an alias change
    reads as add+remove, not a rename).
    """
    ref = str(entry.get("ref") or "")
    if ref:
        return ("ref", str(entry.get("protocol") or ""), ref)
    return ("alias", "", alias)


def _index(alias_map: dict[str, dict]) -> dict[tuple[str, str, str], tuple[str, dict]]:
    """Index a map by tag identity (first alias wins, deterministically)."""
    out: dict[tuple[str, str, str], tuple[str, dict]] = {}
    for alias in sorted(alias_map):
        ident = _identity(alias, alias_map[alias])
        out.setdefault(ident, (alias, alias_map[alias]))
    return out


def _public(alias: str, entry: dict) -> dict[str, str]:
    """A flat, JSON-safe view of an added/removed tag."""
    return {"alias": alias, **{f: str(entry.get(f) or "") for f in _ENTRY_FIELDS}}


def diff_alias_map(previous: Any, current: Any) -> dict:
    """Diff a stored adopted alias map against a fresh one.

    Reports, by stable (protocol, ref) identity:

      * ``added`` — tags only in ``current``;
      * ``removed`` — tags only in ``previous``;
      * ``renamed`` — same ref, different canonical alias;
      * ``reclassified`` — same ref AND alias, different semantic class.

    Returns ``{added, removed, renamed, reclassified, counts, verdict}`` where
    ``verdict`` is ``stable`` when nothing changed, else ``changed``. Pure — neither
    input is mutated.
    """
    prev = _validate_map(previous, "diff_alias_map previous")
    curr = _validate_map(current, "diff_alias_map current")
    prev_idx = _index(prev)
    curr_idx = _index(curr)

    added, removed, renamed, reclassified = [], [], [], []
    for ident, (alias, entry) in curr_idx.items():
        if ident not in prev_idx:
            added.append(_public(alias, entry))
            continue
        palias, pentry = prev_idx[ident]
        if alias != palias:
            renamed.append(
                {
                    "protocol": str(entry.get("protocol") or ""),
                    "ref": str(entry.get("ref") or ""),
                    "from": palias,
                    "to": alias,
                }
            )
        elif str(pentry.get("class") or "") != str(entry.get("class") or ""):
            reclassified.append(
                {
                    "alias": alias,
                    "protocol": str(entry.get("protocol") or ""),
                    "ref": str(entry.get("ref") or ""),
                    "from": str(pentry.get("class") or ""),
                    "to": str(entry.get("class") or ""),
                }
            )
    for ident, (alias, entry) in prev_idx.items():
        if ident not in curr_idx:
            removed.append(_public(alias, entry))

    added.sort(key=lambda d: d["alias"])
    removed.sort(key=lambda d: d["alias"])
    renamed.sort(key=lambda d: (d["ref"], d["to"]))
    reclassified.sort(key=lambda d: d["alias"])

    counts = {
        "added": len(added),
        "removed": len(removed),
        "renamed": len(renamed),
        "reclassified": len(reclassified),
    }
    return {
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "reclassified": reclassified,
        "counts": counts,
        "verdict": "changed" if any(counts.values()) else "stable",
    }


__all__ = [
    "extract_alias_map",
    "save_alias_map",
    "load_alias_map",
    "list_sites",
    "diff_alias_map",
]
