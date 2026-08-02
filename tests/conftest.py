"""Shared test fixtures — IAIOPS_HOME isolation + full-surface tool registry.

Every ``@governed_tool`` call writes to the tamper-evident audit chain and the
policy / budget / pattern / undo stores under ``IAIOPS_HOME`` (default
``~/.iaiops``). Without isolation, tests that exercise governed tools pollute
the developer's REAL harness state and share process-global singletons across
tests (order-dependent budgets, cross-test audit rows). The autouse fixture
below gives every test a fresh throwaway home and fresh singletons.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from iaiops.core.governance.audit import reset_engine
from iaiops.core.governance.budget import reset_budget
from iaiops.core.governance.patterns import reset_pattern_engine
from iaiops.core.governance.policy import reset_policy_engine
from iaiops.core.governance.undo import reset_undo_store


def _reset_governance_singletons() -> None:
    """Drop every process-global governance singleton (rebuilt lazily on use)."""
    reset_engine()
    reset_policy_engine()
    reset_budget()
    reset_pattern_engine()
    reset_undo_store()


@pytest.fixture(autouse=True)
def isolated_iaiops_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point IAIOPS_HOME at a per-test tmp dir and reset governance singletons.

    This is a *default*: a test (or a module-level fixture such as the one in
    ``test_approval_tokens.py``) that sets its own ``IAIOPS_HOME`` and calls the
    reset functions runs after this fixture and simply wins — the two compose.
    The legacy ``OT_AIOPS_HOME`` fallback is cleared so a developer's shell
    environment can never redirect a test back to real state.
    """
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    monkeypatch.delenv("OT_AIOPS_HOME", raising=False)
    _reset_governance_singletons()
    yield tmp_path
    _reset_governance_singletons()


def register_full_tool_surface() -> dict[str, Any]:
    """Register the TRUE full MCP tool surface and return the live registry.

    ``register_profile("all")`` expands to ``tuple(PROTOCOL_MODULES)`` — the
    protocol groups plus the always-on brain. It does NOT load the per-edition
    tool modules (``EDITION_MODULES``: bas / ignition / clinical / building /
    factory / water / process / fab / renewables / warehouse), which include
    the high-risk write ``bas_command``. Contract tests must iterate the
    editions too, or ~25 tools ship without annotation / governance checks.
    """
    from mcp_server import _shared
    from mcp_server.profiles import EDITION_MODULES
    from mcp_server.server import register_profile

    register_profile("all")
    for edition in EDITION_MODULES:
        register_profile(edition)
    return dict(_shared.mcp._tool_manager._tools)


@pytest.fixture
def full_tool_registry() -> dict[str, Any]:
    """The complete registered tool surface: brain + all protocols + all editions."""
    return register_full_tool_surface()


# ─── live-test enforcement (IAIOPS_REQUIRE_LIVE) ─────────────────────────────

_SKIPPED_WHEN_REQUIRED: list[str] = []


def _live_required() -> bool:
    return os.environ.get("IAIOPS_REQUIRE_LIVE", "").strip().lower() in ("1", "true", "yes")


def pytest_collectreport(report: Any) -> None:
    """Catch a MODULE-level skip — the one that leaves no test items behind.

    `pytest.skip(..., allow_module_level=True)` fires during collection, so a
    per-test hook never sees it: the file contributes zero items and the run
    still exits 0. That is exactly how a client library that stops importing
    (pnio-dcp off Linux, an SDK that moved a submodule) would turn a dedicated
    CI step into a silent no-op.
    """
    if _live_required() and report.skipped:
        _SKIPPED_WHEN_REQUIRED.append(f"collection: {report.nodeid or '<module>'}")


def pytest_runtest_logreport(report: Any) -> None:
    # `optional_live` is the one escape hatch: a test whose scaffolding the CI
    # workflow itself declares non-fatal (today only the TDengine native client,
    # whose libtaos comes from a vendor CDN the build deliberately tolerates
    # losing). Marking it is a decision recorded in the test file, not a silent
    # exception buried in the runner.
    if not (_live_required() and report.skipped and report.when in ("setup", "call")):
        return
    if "optional_live" in getattr(report, "keywords", {}):
        return
    _SKIPPED_WHEN_REQUIRED.append(report.nodeid)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Fail the run when a live-promised step skipped anything.

    A CI step that exists solely to run one live file proves nothing if every
    test in it skips: `pytest -q -rs` prints "6 skipped" and **exits 0**, so a
    dropped `export` in a harness script, a renamed env var, or an import that
    started failing quietly converts the step into a no-op while
    `docs/VERIFICATION-RECORD.md` keeps claiming the rung. Same failure mode the
    `-rs` flag was added to surface one level down.

    `IAIOPS_REQUIRE_LIVE=1` is set by exactly those steps (the PROFINET veth
    harness, the BACnet two-IP harness, the integration lane). It says: the
    scaffolding is up, so a skip here is a regression, not an environment.
    Ordinary developer runs are untouched — unset, and skipping on a laptop
    without a broker stays correct.
    """
    if not (_live_required() and _SKIPPED_WHEN_REQUIRED):
        return
    listed = "\n  - ".join(_SKIPPED_WHEN_REQUIRED)
    print(  # noqa: T201 — this has to reach the CI log
        f"\nIAIOPS_REQUIRE_LIVE=1 but {len(_SKIPPED_WHEN_REQUIRED)} test(s) skipped "
        f"where the scaffolding was promised to be up:\n  - {listed}"
    )
    session.exitstatus = 1
