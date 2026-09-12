"""The period `oee measure` measures when nobody names one.

The defect this file was opened for: collection went blind for the last 24s of a
40s run, `iaiops collect run` said so, and `iaiops oee measure <endpoint>` then
reported "92.27% over 100% coverage, blind 0ms". Nothing lied — the default
period was first-sample-to-last-sample, and the blindness is after the last
sample, so it fell outside the window the report chose for itself.

It matters most for MQTT, where a dead publisher is SILENT: there is no
connection error, the subscription stays healthy, and the only evidence is
samples that stop arriving. `connectors/sparkplug/tap.py` refuses to serve a
stale point precisely so that silence becomes a gap; losing that gap one layer up
puts the flattering number back.

The rule under test: **the default period is the one we set out to observe, not
the one we happened to receive data in.**
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain.oee_measure import measure_availability
from iaiops.core.runtime.config import MonitorTag, TagRole

pytestmark = pytest.mark.unit

T0 = datetime(2026, 9, 12, 13, 0, 0, tzinfo=UTC)
RUN_TAG = MonitorTag(ref="plant/l1/run", role=TagRole.RUN_STATE, running_when=(1,))


def _samples(start: datetime, count: int, step_s: float = 1.0):
    """A healthy run-state series: one sample a second, always running."""
    return [
        {"tag": RUN_TAG.ref, "value": 1, "ts": (start + timedelta(seconds=i * step_s)).isoformat()}
        for i in range(count)
    ]


class TestTheDefaultWindowComesFromWhatWeSetOutToObserve:
    def test_a_publisher_that_dies_at_the_end_is_visible_without_naming_a_window(self, tmp_path):
        """The reported defect, end to end through the session record.

        Forty seconds were planned; the publisher went quiet after fifteen. The
        default report must not describe the fifteen as if they were the forty.
        """
        from iaiops.core.collect.plan import CollectionPlan
        from iaiops.core.collect.session import Session, observation_window, save_session

        save_session(
            Session(
                run_id="run-a",
                plan=CollectionPlan(
                    endpoint="uns-1", tags=(RUN_TAG.ref,), duration_s=40, interval_ms=1000
                ),
                started_at=T0.isoformat(),
            ),
            base_dir=tmp_path,
        )
        window = observation_window("uns-1", now=T0 + timedelta(seconds=120), base_dir=tmp_path)
        assert window is not None
        result = measure_availability(_samples(T0, 15), RUN_TAG, window=(window.start, window.end))
        assert result["unknown_s"] > 20, result
        assert result["coverage_pct"] < 50, result
        assert result["status"] != "ok", "26% coverage must not produce a figure"

    def test_the_same_series_over_the_sample_span_hides_it(self, tmp_path):
        """The old behaviour, pinned so the difference is visible and stays so."""
        result = measure_availability(_samples(T0, 15), RUN_TAG, window=None)
        assert result["unknown_s"] == 0.0
        assert result["coverage_pct"] == 100.0


class TestObservationWindow:
    def _save(self, tmp_path, run_id, endpoint, start, duration_s):
        from iaiops.core.collect.plan import CollectionPlan
        from iaiops.core.collect.session import Session, save_session

        save_session(
            Session(
                run_id=run_id,
                plan=CollectionPlan(
                    endpoint=endpoint, tags=("t",), duration_s=duration_s, interval_ms=1000
                ),
                started_at=start.isoformat(),
            ),
            base_dir=tmp_path,
        )

    def test_it_is_the_newest_run_not_the_union_of_all_of_them(self, tmp_path):
        """Two assessments a month apart are two questions. Spanning them makes
        the idle month blind and answers neither — which is why `--since/--until`
        exists (see `measure_availability`'s own docstring)."""
        from iaiops.core.collect.session import observation_window

        self._save(tmp_path, "old", "e1", T0 - timedelta(days=30), 600)
        self._save(tmp_path, "new", "e1", T0, 600)
        window = observation_window("e1", now=T0 + timedelta(days=1), base_dir=tmp_path)
        assert window.start == T0.isoformat()
        assert window.run_id == "new"

    def test_a_run_still_in_progress_is_measured_up_to_now_not_to_its_deadline(self, tmp_path):
        """Counting the not-yet-happened remainder as blind would report a run in
        progress as mostly unobserved, which is the opposite flattering error."""
        from iaiops.core.collect.session import observation_window

        self._save(tmp_path, "live", "e1", T0, 3600)
        now = T0 + timedelta(seconds=600)
        window = observation_window("e1", now=now, base_dir=tmp_path)
        assert window.end == now.isoformat()
        assert window.clamped_to_now is True

    def test_another_endpoints_run_is_not_borrowed(self, tmp_path):
        from iaiops.core.collect.session import observation_window

        self._save(tmp_path, "other", "e2", T0, 600)
        assert observation_window("e1", now=T0 + timedelta(days=1), base_dir=tmp_path) is None

    def test_no_sessions_at_all_means_no_window_rather_than_an_invented_one(self, tmp_path):
        """Imported samples and historian reads have no session. Inventing a
        period for them would be a guess about what somebody meant to observe."""
        from iaiops.core.collect.session import observation_window

        assert observation_window("e1", now=T0, base_dir=tmp_path) is None


class TestTestsCannotReachRealState:
    """The isolation itself, guarded — because nothing else exercises it.

    `CONFIG_DIR` is a SECOND root next to `IAIOPS_HOME`, bound at import from
    `Path.home()`, and the autouse fixture moved only the first one for a long
    time. Collection sessions and the knowledge store live under CONFIG_DIR, so a
    test that did not pass `base_dir` read the developer's real `~/.iaiops` —
    which made a local run and CI disagree whenever the developer had real data,
    and did let a verification run write a session into a real store once.

    Every test in this file passes `base_dir` explicitly, so none of them would
    notice the fixture being removed. This one would.
    """

    def test_config_dir_is_not_the_developers_real_home_during_a_test(self):
        from pathlib import Path

        from iaiops.core.runtime import config as config_mod

        real = Path.home() / ".iaiops"
        assert Path(config_mod.CONFIG_DIR) != real, (
            "CONFIG_DIR points at the real ~/.iaiops during tests — sessions and "
            "the knowledge store written here land in real state"
        )

    def test_the_session_store_resolves_under_the_isolated_root(self, tmp_path):
        from pathlib import Path

        from iaiops.core.collect.session import session_path

        path = session_path("probe-run")
        assert Path.home() not in Path(path).parents, path
