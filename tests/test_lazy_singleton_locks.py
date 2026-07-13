"""Concurrency regression tests for the two lazy caches that back sync MCP tools.

Under the SSE / streamable-http transports, FastMCP runs sync tools concurrently
in a threadpool. ``mcp_server._shared._manager`` and
``iaiops.core.runtime.secretstore.open_store`` are lazy caches that must build
their singleton exactly once even when many threads race the first call —
otherwise ``open_store`` would run the memory-hard KDF repeatedly and hand back
divergent store objects. These tests widen the race window and assert a single
shared instance (and, for the store, a single KDF derivation).
"""

from __future__ import annotations

import threading
import time

import pytest

import iaiops.core.runtime.secretstore as ss
import mcp_server._shared as shared

_THREADS = 24


def _run_concurrently(fn, n: int = _THREADS) -> list:
    """Fire ``fn`` from ``n`` threads released simultaneously; collect results."""
    barrier = threading.Barrier(n)
    results: list = [None] * n
    errors: list = []

    def worker(idx: int) -> None:
        try:
            barrier.wait()
            results[idx] = fn()
        except Exception as exc:  # noqa: BLE001 — surface any thread failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"worker(s) raised: {errors}"
    return results


@pytest.mark.unit
def test_manager_single_instance_under_concurrency(monkeypatch):
    """Many concurrent first-calls to ``_manager`` build exactly one manager."""
    monkeypatch.setattr(shared, "_conn_mgr", None)

    call_count = {"n": 0}
    real_load_config = shared.load_config

    def counting_slow_load_config(path):
        call_count["n"] += 1
        # Widen the window so an unlocked check-then-set would let a second
        # thread in before the first stores the result.
        time.sleep(0.01)
        return real_load_config(path)

    monkeypatch.setattr(shared, "load_config", counting_slow_load_config)

    results = _run_concurrently(shared._manager)

    first = results[0]
    assert all(r is first for r in results), "threads saw divergent managers"
    assert call_count["n"] == 1, f"config loaded {call_count['n']}x — cache raced"


@pytest.mark.unit
def test_open_store_single_instance_and_kdf_once(tmp_path, monkeypatch):
    """Concurrent ``open_store`` calls share one store and derive the key once."""
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv(ss.MASTER_PASSWORD_ENV, "master-pw")

    # A persisted store forces ``unlock`` down the decrypt path (which runs the
    # KDF); a fresh/nonexistent store would skip derivation entirely.
    ss.SecretStore.unlock("master-pw").set("line1", "plc-pw")

    derive_count = {"n": 0}
    real_derive = ss._derive_key

    def counting_slow_derive(password, salt):
        derive_count["n"] += 1
        time.sleep(0.01)  # widen the race window
        return real_derive(password, salt)

    monkeypatch.setattr(ss, "_derive_key", counting_slow_derive)
    monkeypatch.setattr(ss, "_cached", None)

    results = _run_concurrently(ss.open_store)

    first = results[0]
    assert all(r is first for r in results), "threads saw divergent stores"
    assert derive_count["n"] == 1, f"KDF ran {derive_count['n']}x — the memory-hard unlock raced"


@pytest.mark.unit
def test_open_store_bypasses_cache_with_explicit_password(tmp_path, monkeypatch):
    """An explicit password / use_cache=False must not populate or read the cache."""
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)

    ss.SecretStore.unlock("master-pw").set("line1", "plc-pw")

    s1 = ss.open_store("master-pw")
    s2 = ss.open_store("master-pw")
    assert s1 is not s2, "explicit password must bypass the cache"
    assert ss._cached is None, "explicit password must not populate the cache"
