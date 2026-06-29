"""Home-directory resolution for the governance harness.

State lives under ``ops_home()`` — by default ``~/.iaiops``, overridable
via the ``IAIOPS_HOME`` environment variable so an operator can relocate
the audit / policy / budget / undo store.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_HOME = "~/.iaiops"
_LEGACY_HOME = "~/.ot-aiops"  # pre-rename location; honored as fallback for existing installs
_LEGACY_HOME_ENV = "OT_AIOPS_HOME"  # pre-rename env var
# Files whose presence means a home dir actually holds harness state. The legacy
# fallback keys on these (not bare directory existence) so a stray-but-empty
# ``~/.iaiops`` cannot silently shadow a populated legacy ``~/.ot-aiops``.
_STATE_MARKERS = ("audit.db", "secrets.enc")


def _has_state(d: Path) -> bool:
    return d.is_dir() and any((d / m).exists() for m in _STATE_MARKERS)


def ops_home() -> Path:
    """Return the harness state directory.

    Precedence: ``IAIOPS_HOME`` → legacy ``OT_AIOPS_HOME`` → ``~/.iaiops``.
    If neither env override is set and ``~/.iaiops`` holds no state yet but the
    legacy ``~/.ot-aiops`` does, the legacy directory is used so existing audit /
    secrets / undo state keeps working after the rename.
    """
    override = os.environ.get("IAIOPS_HOME") or os.environ.get(_LEGACY_HOME_ENV)
    if override:
        return Path(override).expanduser()
    new_home = Path(_DEFAULT_HOME).expanduser()
    if not _has_state(new_home) and _has_state(Path(_LEGACY_HOME).expanduser()):
        return Path(_LEGACY_HOME).expanduser()
    return new_home


def ops_path(*parts: str) -> Path:
    """Resolve a file under the harness home, e.g. ``ops_path('audit.db')``."""
    return ops_home().joinpath(*parts)
