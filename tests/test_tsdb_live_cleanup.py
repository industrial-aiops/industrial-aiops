"""The live TSDB tests must not leave databases behind on the server.

Found 2026-08-26 on the lab TDengine (192.168.60.237). Five leftover databases
named `iaiops_tr_*` had accumulated from earlier runs, and the server started
refusing new writes with:

    [0x03BA] Internal error: `Vnodes exhausted`

which surfaced twice as what looked like a product failure — once mid-way
through verifying an unrelated fix — until the stale databases were dropped by
hand. A test that poisons the server for every later run is worse than a test
that fails.

The cause was not flaky teardown. `test_tdengine_round_trip_over_a_libtaos_free_transport`
built its database name **inline** and had no cleanup at all, so every run leaked
one per transport parameter. It could not simply use the `tdengine_database`
fixture, because that fixture cleans up through the NATIVE client and would
therefore skip on exactly the machines the transport tests exist to cover.

These tests cover the two pure decisions, and they matter more than they look:
**the sweeper's pattern decides what gets DROPPED**, so anything it matches by
accident is somebody's data.
"""

from __future__ import annotations

import os

import pytest
import test_tsdb_live as live
from test_tsdb_live import _is_sweepable, _is_throwaway_name, _unique

pytestmark = pytest.mark.unit


class TestTheSweeperOnlyMatchesOurOwnScratchDatabases:
    @pytest.mark.parametrize("prefix", ["iaiops_test_", "iaiops_tr_"])
    def test_it_matches_what_unique_actually_produces(self, prefix):
        """Pinned against the generator rather than a hand-written example, so a
        change to `_unique` cannot silently stop the sweeper matching."""
        assert _is_throwaway_name(_unique(prefix))

    @pytest.mark.parametrize(
        "name",
        [
            "iaiops",  # the DEFAULT database name — a real site's data
            "iaiops_test",  # no run suffix: not ours
            "iaiops_tr",
            "iaiops_prod_1_2",  # our shape, not our prefix
            "rcatest",
            "information_schema",
            "performance_schema",
            "log",
            "",
            "iaiops_test_abc_def",  # letters where the run ids go
            "xiaiops_test_1_2",  # prefix must anchor at the start
            "iaiops_test_1_2_extra",
        ],
    )
    def test_it_refuses_everything_else(self, name):
        """The load-bearing half. A sweeper that over-matches deletes production
        data, which is a far worse failure than the leak it is fixing."""
        assert not _is_throwaway_name(name)

    def test_the_default_sink_database_can_never_match(self):
        """Stated separately because it is the specific catastrophe: `iaiops` is
        what `TDengineSink` uses when a site does not name one."""
        from iaiops.core.sink.tdengine import TDengineSink

        default = TDengineSink.__init__.__defaults__
        assert "iaiops" in default, "the default database name moved — recheck this guard"
        assert not _is_throwaway_name("iaiops")


class TestItErrsTowardLeakingRatherThanDestroying:
    """A leftover database costs a `DROP`. A wrongly-dropped one costs the data.
    Every uncertain case must resolve the first way."""

    def test_a_database_belonging_to_a_running_process_is_left_alone(self):
        """Two pytest sessions can share one lab server. Sweeping a name whose
        pid is still running would delete the other session's database out from
        under a test that is mid-flight."""
        mine = _unique("iaiops_tr_")
        assert _is_throwaway_name(mine), "the fixture name must match, or this proves nothing"
        assert not _is_sweepable(mine), "our own live pid must be excluded"

    def test_a_database_from_a_dead_process_is_swept(self):
        """The complement: excluding everything would pass the test above and
        leave the leak exactly as it was."""
        dead = f"iaiops_tr_{_dead_pid()}_123456"
        assert _is_sweepable(dead)

    def test_a_name_that_is_not_ours_is_never_sweepable_whatever_the_pid(self):
        assert not _is_sweepable(f"iaiops_prod_{_dead_pid()}_123456")
        assert not _is_sweepable("iaiops")


def _dead_pid() -> int:
    """A pid that is not running. Searched rather than assumed — a hard-coded
    'obviously free' number is a test that passes until the day it does not."""
    for candidate in range(_MAX_PID, _MAX_PID - 5000, -1):
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            continue
    pytest.skip("could not find a dead pid to test with")


_MAX_PID = 99_998


class TestCleanupIsQuietOnAMachineWithNoServer:
    """The common case — every developer box without a TSDB, and most of CI.

    The first version of this teardown ran regardless, could not reach anything,
    and warned twice per run about failing to drop a database that was never
    created because the test had skipped. A cleanup that cries wolf on a healthy
    machine is one people learn to ignore on a sick one.
    """

    def test_it_says_nothing_when_no_server_was_reachable(self, monkeypatch, recwarn):
        monkeypatch.setattr(live, "_HAS_TAOS_ADAPTER", False)
        monkeypatch.setattr(live, "_HAS_TAOS", False)
        monkeypatch.setattr(
            live, "_any_tdengine_connection", _fail("teardown must not even try to connect")
        )
        live._drop_tdengine_database(_unique("iaiops_tr_"))
        assert [str(w.message) for w in recwarn] == []

    def test_it_does_warn_when_a_server_was_there_and_the_drop_failed(self, monkeypatch, recwarn):
        """The complement. Silence must come from "nothing could have been
        created", never from "we gave up on saying so"."""
        monkeypatch.setattr(live, "_HAS_TAOS_ADAPTER", True)
        monkeypatch.setattr(live, "_any_tdengine_connection", lambda database="": None)
        live._drop_tdengine_database(_unique("iaiops_tr_"))
        assert any("could not reach" in str(w.message) for w in recwarn), [
            str(w.message) for w in recwarn
        ]

    def test_it_refuses_to_drop_a_name_that_is_not_scratch(self, monkeypatch):
        """The last line of defence before a DROP: even called directly with a
        real database name, it must not proceed."""
        monkeypatch.setattr(live, "_HAS_TAOS_ADAPTER", True)
        monkeypatch.setattr(live, "_any_tdengine_connection", _fail("must not connect"))
        with pytest.raises(AssertionError, match="not a scratch database"):
            live._drop_tdengine_database("iaiops")


def _fail(message: str):
    def _boom(*_args, **_kwargs):
        raise AssertionError(message)

    return _boom
