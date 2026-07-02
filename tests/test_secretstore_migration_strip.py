"""Legacy .env migration must not leave plaintext secret values on disk."""

from __future__ import annotations

import pytest

import iaiops.core.runtime.secretstore as ss


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """Point the secret store at a throwaway directory."""
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    return tmp_path


@pytest.mark.unit
def test_migrated_env_has_values_stripped(store_dir):
    (store_dir / ".env").write_text(
        "OT_LINE1_PASSWORD=super-secret-1\n"
        "# a comment\n"
        "OT_LINE2_PASSWORD='quoted-secret'\n"
        "UNRELATED=also-gone\n"
    )
    imported = ss.migrate_legacy_env("OT_", "_PASSWORD", "master-pw")
    assert sorted(imported) == ["line1", "line2"]

    assert not (store_dir / ".env").exists()
    migrated = (store_dir / ".env.migrated").read_text("utf-8")
    # no plaintext value survives — not even non-matching keys' values
    for secret in ("super-secret-1", "quoted-secret", "also-gone"):
        assert secret not in migrated
    # key names remain so the operator can see WHAT was migrated
    assert "OT_LINE1_PASSWORD=" in migrated
    assert "OT_LINE2_PASSWORD=" in migrated
    assert "UNRELATED=" in migrated
    assert "encrypted secret store" in migrated  # the teaching header

    # the secrets really made it into the encrypted store
    reopened = ss.SecretStore.unlock("master-pw")
    assert reopened.get("line1") == "super-secret-1"
    assert reopened.get("line2") == "quoted-secret"


@pytest.mark.unit
def test_strip_env_values_preserves_comments_and_blanks():
    raw = "# keep me\n\nKEY=value\n"
    out = ss._strip_env_values(raw)
    assert "# keep me" in out
    assert "KEY=" in out
    assert "value" not in out.replace("values were stripped", "")


@pytest.mark.unit
def test_no_migration_leaves_env_untouched(store_dir):
    (store_dir / ".env").write_text("SOMETHING_ELSE=keep\n")
    imported = ss.migrate_legacy_env("OT_", "_PASSWORD", "master-pw")
    assert imported == []
    assert (store_dir / ".env").exists()  # nothing imported → nothing rewritten
    assert not (store_dir / ".env.migrated").exists()
