"""Encrypted secret storage for iaiops.

Secrets (per-endpoint OPC-UA / Modbus passwords) are NEVER written to disk in
plaintext. They live in ``~/.iaiops/secrets.enc`` encrypted with Fernet
(AES-128-CBC + HMAC-SHA256). The Fernet key is derived from a master password
via scrypt — the password itself is never stored; only a random per-store salt
and the ciphertext are on disk.

Secrets are keyed by the endpoint target name (e.g. ``line1``).

The master password is resolved (in order) from:

  1. the env var ``IAIOPS_MASTER_PASSWORD`` (for non-interactive use:
     the MCP server, CI, cron), or
  2. an interactive ``getpass`` prompt (CLI on a TTY).

This module is deliberately self-contained (no skill-family imports) so it can
be vendored per tool exactly like the governance harness.

Design rules honoured here:
  * Immutability — the decrypted secret map is never mutated in place; every
    ``set``/``delete`` derives a new dict and re-encrypts it.
  * Fail fast with teaching errors at the trust boundary.
  * Owner-only files (chmod 600 on the blob, 700 on the dir).
"""

from __future__ import annotations

import base64
import getpass
import json
import logging
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidKey
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from iaiops.core.governance.paths import ops_home

# ─── Tool-specific constants (change these three to vendor for another tool) ──
APP_NAME = "iaiops"
# Secrets live alongside the rest of the harness state. ops_home() centralizes the
# IAIOPS_HOME override + legacy ~/.ot-aiops fallback, so audit/budget/undo and
# secrets never split-brain across two directories.
CONFIG_DIR = ops_home()
MASTER_PASSWORD_ENV = "IAIOPS_MASTER_PASSWORD"  # nosec B105 — env var name, not a secret
_LEGACY_MASTER_PASSWORD_ENV = "OT_AIOPS_MASTER_PASSWORD"  # nosec B105 — pre-rename fallback
# ──────────────────────────────────────────────────────────────────────────────

SECRETS_FILE = CONFIG_DIR / "secrets.enc"
LEGACY_ENV_FILE = CONFIG_DIR / ".env"

# scrypt work factors (RFC 7914). N must be a power of two; these give ~100ms
# on commodity hardware — strong for an interactive unlock, cheap enough to run
# once per process.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32
_SALT_LEN = 16
_FORMAT_VERSION = 1

_log = logging.getLogger(f"{APP_NAME}.secretstore")


class SecretStoreError(Exception):
    """A secret could not be stored or retrieved; carries a teaching message."""


class MasterPasswordError(SecretStoreError):
    """The master password is missing or wrong."""


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a urlsafe-base64 Fernet key from a password + salt via scrypt."""
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    raw = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def _chmod_600(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:  # best effort on exotic filesystems
        pass


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass


def resolve_master_password(*, confirm_if_new: bool = False) -> str:
    """Resolve the master password from env or an interactive prompt.

    ``confirm_if_new`` asks twice when no store exists yet (set-up flow).
    Raises ``MasterPasswordError`` when no password is available and there is no
    TTY to prompt on (e.g. an MCP server started without the env var).
    """
    env_value = os.environ.get(MASTER_PASSWORD_ENV) or os.environ.get(_LEGACY_MASTER_PASSWORD_ENV)
    if env_value:
        return env_value

    if not sys.stdin.isatty():
        raise MasterPasswordError(
            f"Master password not set. Export {MASTER_PASSWORD_ENV} (the password "
            f"that unlocks {SECRETS_FILE}) before running non-interactively, or "
            f"run '{APP_NAME} init' on a terminal to set up secrets."
        )

    store_exists = SECRETS_FILE.exists()
    prompt = f"Master password for {APP_NAME}: "
    password = getpass.getpass(prompt)
    if not password:
        raise MasterPasswordError("Empty master password is not allowed.")
    if confirm_if_new and not store_exists:
        again = getpass.getpass("Confirm master password: ")
        if again != password:
            raise MasterPasswordError("Passwords did not match. Aborted.")
    return password


@dataclass(frozen=True)
class SecretStore:
    """An unlocked view over the encrypted secret file.

    Construct via :meth:`unlock` (or :func:`open_store`). The decrypted map is
    held in memory only; every mutation returns a *new* ``SecretStore`` after
    re-encrypting to disk — instances are immutable.
    """

    _password: str
    _salt: bytes
    _data: dict[str, str]

    # ── factory ────────────────────────────────────────────────────────────
    @classmethod
    def unlock(cls, password: str | None = None) -> SecretStore:
        """Open (or initialise) the store, decrypting with ``password``."""
        pw = password if password is not None else resolve_master_password()
        if not SECRETS_FILE.exists():
            return cls(_password=pw, _salt=os.urandom(_SALT_LEN), _data={})

        try:
            raw = json.loads(SECRETS_FILE.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise SecretStoreError(
                f"Could not read secret store {SECRETS_FILE}: {exc}"
            ) from exc

        if raw.get("version") != _FORMAT_VERSION:
            raise SecretStoreError(
                f"Unsupported secret store version {raw.get('version')!r} in "
                f"{SECRETS_FILE}; expected {_FORMAT_VERSION}."
            )
        salt = base64.b64decode(raw["salt"])
        token = raw["ciphertext"].encode("ascii")
        try:
            key = _derive_key(pw, salt)
            plaintext = Fernet(key).decrypt(token)
        except (InvalidToken, InvalidKey, ValueError) as exc:
            raise MasterPasswordError(
                "Wrong master password (could not decrypt the secret store). "
                f"If you forgot it, delete {SECRETS_FILE} and re-run "
                f"'{APP_NAME} init' to re-enter credentials."
            ) from exc
        data = json.loads(plaintext.decode("utf-8"))
        return cls(_password=pw, _salt=salt, _data=dict(data))

    # ── read ──────────────────────────────────────────────────────────────
    def get(self, name: str) -> str:
        try:
            return self._data[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._data)) or "(none)"
            raise SecretStoreError(
                f"No secret stored for '{name}'. Stored: {available}. "
                f"Add one with '{APP_NAME} secret set {name}'."
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._data))

    def __contains__(self, name: object) -> bool:
        return name in self._data

    # ── write (returns a new immutable store) ──────────────────────────────
    def set(self, name: str, value: str) -> SecretStore:
        if not name:
            raise SecretStoreError("Secret name must not be empty.")
        if not value:
            raise SecretStoreError("Secret value must not be empty.")
        new_data = {**self._data, name: value}
        new_store = SecretStore(_password=self._password, _salt=self._salt, _data=new_data)
        new_store._persist()
        return new_store

    def delete(self, name: str) -> SecretStore:
        if name not in self._data:
            raise SecretStoreError(f"No secret named '{name}' to delete.")
        new_data = {k: v for k, v in self._data.items() if k != name}
        new_store = SecretStore(_password=self._password, _salt=self._salt, _data=new_data)
        new_store._persist()
        return new_store

    def with_password(self, new_password: str) -> SecretStore:
        """Re-encrypt all secrets under a new master password (rotation)."""
        if not new_password:
            raise SecretStoreError("New master password must not be empty.")
        new_store = SecretStore(
            _password=new_password, _salt=os.urandom(_SALT_LEN), _data=dict(self._data)
        )
        new_store._persist()
        return new_store

    # ── persistence ────────────────────────────────────────────────────────
    def _persist(self) -> None:
        _ensure_dir()
        key = _derive_key(self._password, self._salt)
        token = Fernet(key).encrypt(json.dumps(self._data).encode("utf-8"))
        blob = json.dumps(
            {
                "version": _FORMAT_VERSION,
                "salt": base64.b64encode(self._salt).decode("ascii"),
                "ciphertext": token.decode("ascii"),
            },
            indent=2,
        )
        tmp = SECRETS_FILE.with_suffix(".enc.tmp")
        tmp.write_text(blob, "utf-8")
        _chmod_600(tmp)
        tmp.replace(SECRETS_FILE)
        _chmod_600(SECRETS_FILE)


# ─── module-level convenience API (the rest of the app uses these) ───────────

_cached: SecretStore | None = None


def open_store(password: str | None = None, *, use_cache: bool = True) -> SecretStore:
    """Return an unlocked store, caching it for the process when possible."""
    global _cached  # noqa: PLW0603
    if use_cache and _cached is not None and password is None:
        return _cached
    store = SecretStore.unlock(password)
    if use_cache and password is None:
        _cached = store
    return store


def get_secret(name: str) -> str:
    """Look up a secret by name, unlocking the store on first use."""
    return open_store().get(name)


def has_store() -> bool:
    return SECRETS_FILE.exists()


def check_permissions() -> str | None:
    """Return a warning string if ``secrets.enc`` is group/world-accessible."""
    if not SECRETS_FILE.exists():
        return None
    mode = SECRETS_FILE.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return (
            f"{SECRETS_FILE} has permissions {oct(stat.S_IMODE(mode))} "
            f"(should be 600). Run: chmod 600 {SECRETS_FILE}"
        )
    return None


def migrate_legacy_env(prefix: str, suffix: str, password: str | None = None) -> list[str]:
    """Import plaintext ``.env`` secrets into the encrypted store.

    Per-endpoint legacy keys look like ``OT_<NAME>_PASSWORD``;
    ``prefix='OPCUA_'`` and ``suffix='_PASSWORD'`` map them back to a target
    name. The plaintext ``.env`` is renamed to ``.env.migrated`` (chmod 600) so
    nothing is silently lost. Returns the list of imported secret names.
    """
    if not LEGACY_ENV_FILE.exists():
        return []
    imported: list[str] = []
    store = SecretStore.unlock(password)
    for line in LEGACY_ENV_FILE.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if not value:
            continue
        if key.startswith(prefix) and key.endswith(suffix):
            target = key[len(prefix) : -len(suffix)].lower().replace("_", "-")
            if target:
                store = store.set(target, value)
                imported.append(target)
    if imported:
        backup = LEGACY_ENV_FILE.with_name(".env.migrated")
        LEGACY_ENV_FILE.replace(backup)
        _chmod_600(backup)
    return imported
