"""A stamp over a sheet's companion-spec suggestion columns (HLD §10.1, D49).

``tags apply`` credits a row to the device's declaration (``basis:
companion_spec``) when the person set exactly what the read-only ``suggested_*``
columns say. Those columns travel in a CSV the proposer controls, so until this
existed anyone could TYPE them and get the credit — and the patch, and any
signed release built on it, would then say "the device declared this". That is
the flattering error in its purest form: a manual call wearing a device's name.

So ``tags export --suggest`` stamps each suggested row: an HMAC-SHA256 over
``(endpoint, ref, suggested_role, suggested_running_when, suggestion_evidence)``
under a per-site key kept in ``$IAIOPS_HOME`` (created on first use, owner-only,
never in a repo). ``validate_rows`` checks it. A row that does not verify is
DOWNGRADED to ``companion_spec_unverified`` — never refused: the person's call
is still a call, it just is not the device's.

What a verified stamp proves, and what it does not:

* It proves the five columns are byte-for-byte (whitespace folded) what an
  ``export --suggest`` on a host holding THIS site's key wrote for THIS
  endpoint and ref. Hand-typed columns, a suggestion moved to another row, an
  edited running value, another site's sheet and a pre-stamp sheet all fail.
* It does NOT prove the device still declares it: nothing is re-read at
  ``apply``. And the key is a SITE secret, not a person's: whoever can read
  ``$IAIOPS_HOME`` can mint a stamp. It separates "came out of the export" from
  "typed into the file", which is the gap a sheet passed between people opens.

Deleting the key file voids every outstanding sheet's stamps (they read as
unverified, not refused) — that is rotation. A key file of the wrong size is
refused rather than replaced, because replacing it would void them silently.

``stamp`` / ``check`` are [PURE]; only ``site_key`` touches the filesystem.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iaiops.core.governance.paths import ops_home, ops_path

KEY_FILE = "tag_suggestion.key"
KEY_BYTES = 32
_VERSION = "v1"
_DOMAIN = "iaiops.tag_suggestion"
#: The columns the stamp covers. ``role`` / ``running_when`` are deliberately
#: NOT here: filling them is what the person is supposed to do.
_FIELDS = (
    "endpoint",
    "ref",
    "suggested_role",
    "suggested_running_when",
    "suggestion_evidence",
)

#: ``check`` outcomes. Only ``VERIFIED`` earns ``basis: companion_spec``.
VERIFIED = "verified"
MISSING = "missing"
MISMATCH = "mismatch"
OTHER_KEY = "other_key"
NO_KEY = "no_key"

__all__ = [
    "KEY_BYTES",
    "KEY_FILE",
    "MISMATCH",
    "MISSING",
    "NO_KEY",
    "OTHER_KEY",
    "StampKeyError",
    "VERIFIED",
    "check",
    "site_key",
    "stamp",
]


class StampKeyError(ValueError):
    """The site's stamp key exists but cannot be used; carries a teaching message.

    A ``ValueError`` so the CLI prints the message as one line instead of a
    traceback that hides it.
    """


def _key_id(key: bytes) -> str:
    """Eight hex chars naming the key — so another site's sheet can be SAID to be one."""
    return hashlib.sha256(_DOMAIN.encode() + b".key-id" + key).hexdigest()[:8]


def _message(row: Mapping[str, Any]) -> bytes:
    # JSON, not a joined string: no choice of separator survives a field that
    # contains it. Whitespace is folded because spreadsheets pad and wrap cells.
    fields = [" ".join(str(row.get(name, "") or "").split()) for name in _FIELDS]
    return json.dumps([_DOMAIN, _VERSION, *fields], ensure_ascii=False).encode("utf-8")


def stamp(key: bytes, row: Mapping[str, Any]) -> str:
    """``v1:<key id>:<hmac hex>`` over the row's suggestion columns."""
    mac = hmac.new(key, _message(row), hashlib.sha256).hexdigest()
    return f"{_VERSION}:{_key_id(key)}:{mac}"


def check(key: bytes | None, row: Mapping[str, Any]) -> str:
    """One of the outcome constants. Never raises on what a sheet carries."""
    written = "".join(str(row.get("suggestion_stamp", "") or "").split())
    if not written:
        return MISSING
    if key is None:
        return NO_KEY
    parts = written.split(":")
    if len(parts) != 3 or parts[0] != _VERSION:
        return MISMATCH
    if not hmac.compare_digest(parts[1], _key_id(key)):
        return OTHER_KEY
    return VERIFIED if hmac.compare_digest(written, stamp(key, row)) else MISMATCH


def site_key(create: bool = False) -> bytes | None:
    """This site's stamp key; ``None`` when there is none and ``create`` is false.

    Reading never creates: ``apply`` on a host that never exported has nothing to
    verify against, and inventing a key there would make that look otherwise.
    """
    path = ops_path(KEY_FILE)
    if not path.exists() and create:
        _create(path)
    if not path.exists():
        return None
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise StampKeyError(f"Cannot read the suggestion stamp key {path}: {exc}") from exc
    if len(key) != KEY_BYTES:
        raise StampKeyError(
            f"{path} is not a suggestion stamp key ({len(key)} bytes, expected "
            f"{KEY_BYTES}). It is not replaced automatically — that would void every "
            "stamped sheet without saying so. Delete it to start over (outstanding "
            "sheets then read as `companion_spec_unverified`)."
        )
    return key


def _create(path: Path) -> None:
    home = ops_home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)
    except OSError:  # best effort on exotic filesystems
        pass
    # Written whole to a private temp file, then hard-linked into place: link
    # fails if the key exists, so two exports racing on a fresh site cannot each
    # keep a key (one would hold stamps nothing verifies), and a reader never
    # sees a half-written file.
    tmp = path.with_name(f".{KEY_FILE}.{secrets.token_hex(8)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(KEY_BYTES))
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
    finally:
        tmp.unlink(missing_ok=True)
