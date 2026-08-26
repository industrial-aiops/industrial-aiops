"""A sink nobody can feed is a sink nobody has.

Found 2026-08-26 by walking the shipped demo through two lab VMs — the device on
one machine across a real LAN, TDengine and IoTDB on another. Collection worked.
Then every documented route from "I have collected data" to "it is in my
historian" turned out to be broken, in three independent places:

1. **`historian push` had no way to choose a transport.** It always used the
   native client, which needs `libtaos` — a vendor tarball, not a PyPI wheel. So
   on macOS, and on any air-gapped Linux without that tarball, `push --sink
   tdengine` could not run at all. The REST and WebSocket transports were built
   and working: calling the SAME function with `transport="rest"` wrote 999 of
   999 points to the live lab server. Only the flag was missing. The config
   block had `transport:` for the READ side; the write side could not reach it.

2. **The error that says so was truncated mid-sentence.** `s(str(exc), 200)` cut
   the teaching line at `"It is a ve"` — exactly where it starts explaining the
   way out. A cap on a client library's output is right; capping our own
   remediation sentence is not.

3. **`export` could not produce what `push` consumes.** `export` wrote csv /
   sqlite / parquet; `push --input` wanted a JSON list of points. `docs/CHINA.md`
   said the JSON came "from `iaiops modbus read-holding`" — a command that does
   not exist (it is `holding`), whose output shape `push` rejects anyway with
   "No usable points to write". So the collected history that OEE is measured
   from had no route into the historian at all; the bridge had to be hand-written
   in Python.

None of this was reachable by the test suite, because every existing test called
`historian_push` with a points list built in the test. The customer's actual
route — collect, export, push — was never walked end to end.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from iaiops.core.sink.export import EXPORT_FORMATS, export_samples
from iaiops.core.sink.push import historian_push

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture
def store(tmp_path):
    """A local store holding one collection run's worth of samples."""
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    db = tmp_path / "data.db"
    sink = SQLiteLocalSink(db_path=str(db), endpoint="line1", protocol="modbus")
    sink.write(
        [
            {"metric": "0", "value": 2.0, "timestamp": "2026-08-26T07:47:13.436000+00:00"},
            {"metric": "10", "value": 16.0, "timestamp": "2026-08-26T07:47:13.439000+00:00"},
            {"metric": "11", "value": 15.0, "timestamp": "2026-08-26T07:47:13.443000+00:00"},
        ]
    )
    return db


class TestExportCanProduceWhatPushConsumes:
    """The missing link. Not "json is a nice extra" — without it the collected
    history, which is the ONLY thing `oee measure` reads, cannot reach a
    historian by any supported command."""

    def test_json_is_an_export_format(self):
        assert "json" in EXPORT_FORMATS

    def test_the_exported_file_is_a_list_of_points(self, store, tmp_path):
        out = tmp_path / "points.json"
        export_samples("json", out, db_path=store)
        points = json.loads(out.read_text("utf-8"))
        assert isinstance(points, list) and len(points) == 3

    def test_push_accepts_the_export_verbatim(self, store, tmp_path):
        """The whole point, and the assertion that would have failed before:
        the two halves have to agree on a shape without a converter in between."""
        out = tmp_path / "points.json"
        export_samples("json", out, db_path=store)
        result = historian_push(
            json.loads(out.read_text("utf-8")), "sqlite", db_path=str(tmp_path / "hist.db")
        )
        assert result.get("error") is None, result
        assert result["written"] == 3

    def test_it_carries_the_timestamp_not_just_the_value(self, store, tmp_path):
        """A point without its timestamp is written at import time, silently
        restamping a week of history to one instant."""
        out = tmp_path / "points.json"
        export_samples("json", out, db_path=store)
        points = json.loads(out.read_text("utf-8"))
        assert {p["timestamp"] for p in points} == {
            "2026-08-26T07:47:13.436000+00:00",
            "2026-08-26T07:47:13.439000+00:00",
            "2026-08-26T07:47:13.443000+00:00",
        }

    def test_the_metric_name_survives_the_round_trip(self, store, tmp_path):
        """Modbus refs are bare numbers. `normalize_points` looks for
        `metric`/`ref`; the store column is called `tag`, and a straight dump of
        the row would have been dropped as unusable."""
        out = tmp_path / "points.json"
        export_samples("json", out, db_path=store)
        assert {p["metric"] for p in json.loads(out.read_text("utf-8"))} == {"0", "10", "11"}

    def test_an_empty_store_exports_an_empty_list_not_a_broken_file(self, tmp_path):
        from iaiops.core.sink.sqlite_local import SQLiteLocalSink

        db = tmp_path / "empty.db"
        SQLiteLocalSink(db_path=str(db), endpoint="x", protocol="modbus").write([])
        out = tmp_path / "points.json"
        export_samples("json", out, db_path=db)
        assert json.loads(out.read_text("utf-8")) == []


class TestPushCanChooseATransport:
    """`transport` is the difference between "this product does not run here" and
    "this product runs here". It must be reachable from the command line."""

    def _cli(self, *args):
        from iaiops.cli.compliance import historian_app

        # COLUMNS pinned: rich renders the help into whatever width the terminal
        # reports, and on a narrow one it breaks "--transport" across lines. The
        # first version of this file asserted on the rendered text without it and
        # was green locally, red on CI — a test whose result depended on the
        # window it ran in.
        return runner.invoke(historian_app, list(args), env={"COLUMNS": "200"})

    def test_the_flag_exists(self):
        """Asserted against the declared parameter, not the rendered help, so it
        cannot be defeated by line wrapping."""
        import typer.main

        from iaiops.cli.compliance import historian_app

        push = typer.main.get_command(historian_app).commands["push"]
        assert "--transport" in {opt for p in push.params for opt in p.opts}

    def test_the_help_names_the_transports(self):
        """A flag whose values you have to read the source to learn is a flag
        that gets guessed wrong."""
        out = self._cli("push", "--help").stdout
        assert "rest" in out and "websocket" in out and "native" in out

    def test_it_reaches_the_sink(self, tmp_path, monkeypatch):
        """Recorded at the boundary, because the transports that prove this for
        real need a live TDengine (see tests/test_tsdb_live.py)."""
        seen: dict = {}

        def fake_get_sink(kind, **opts):
            seen.update({"kind": kind, **opts})
            raise ValueError("stop here — we only need the options")

        monkeypatch.setattr("iaiops.core.sink.push.get_sink", fake_get_sink)
        points = tmp_path / "p.json"
        points.write_text(json.dumps([{"metric": "0", "value": 1.0}]), encoding="utf-8")
        self._cli(
            "push",
            "--sink",
            "tdengine",
            "--input",
            str(points),
            "--host",
            "10.0.0.5",
            "--transport",
            "rest",
        )
        assert seen.get("transport") == "rest"

    def test_a_transport_typo_is_refused_with_the_supported_list(self, tmp_path):
        points = tmp_path / "p.json"
        points.write_text(json.dumps([{"metric": "0", "value": 1.0}]), encoding="utf-8")
        out = self._cli(
            "push", "--sink", "tdengine", "--input", str(points), "--transport", "restt"
        )
        assert "rest" in out.stdout

    def test_a_transport_on_a_sink_that_has_none_is_refused_not_ignored(self, tmp_path):
        """IoTDB's sink takes no `transport`; passing one used to be a TypeError
        surfacing as a traceback. Silently dropping it would be worse — the
        operator would believe a transport was selected."""
        points = tmp_path / "p.json"
        points.write_text(json.dumps([{"metric": "0", "value": 1.0}]), encoding="utf-8")
        out = self._cli("push", "--sink", "iotdb", "--input", str(points), "--transport", "rest")
        assert "tdengine" in out.stdout.lower()
        assert "traceback" not in out.stdout.lower()

    def test_omitting_it_still_works(self, tmp_path, monkeypatch):
        """The complement: the flag must be optional, and its absence must not
        start passing `transport=""` into a sink that has no such parameter."""
        seen: dict = {}
        monkeypatch.setattr(
            "iaiops.core.sink.push.get_sink",
            lambda kind, **opts: (seen.update(opts), _raise())[1],
        )
        points = tmp_path / "p.json"
        points.write_text(json.dumps([{"metric": "0", "value": 1.0}]), encoding="utf-8")
        self._cli("push", "--sink", "iotdb", "--input", str(points))
        assert "transport" not in seen


def _raise():
    raise ValueError("stop")


class TestTheErrorSurvivesLongEnoughToBeUseful:
    def test_a_teaching_error_is_not_cut_mid_sentence(self, monkeypatch, tmp_path):
        """The real one, verbatim from the lab run, ended at `"It is a ve"`. The
        sentence it was cutting is the one naming the way out."""
        from iaiops.core.sink.base import SinkError

        long_teaching_error = (
            "The native TDengine client (libtaos) could not be loaded: [0xffff]: unable to "
            "load taos client library: [0xffff]: unable to load taos client library: dylib "
            "libtaos.dylib could not be found. It is a vendor download, not a PyPI wheel — "
            "or use a transport that needs no native library: --transport rest (HTTP :6041) "
            "or --transport websocket."
        )

        def boom(kind, **opts):
            raise SinkError(long_teaching_error)

        monkeypatch.setattr("iaiops.core.sink.push.get_sink", boom)
        result = historian_push([{"metric": "0", "value": 1.0}], "tdengine")
        assert "--transport rest" in result["error"], result["error"]

    def test_it_is_still_bounded(self, monkeypatch):
        """A client library can echo a whole query back. The cap stays — it just
        has to clear our own longest written sentence."""
        from iaiops.core.sink.base import SinkError

        def boom(kind, **opts):
            raise SinkError("x" * 100_000)

        monkeypatch.setattr("iaiops.core.sink.push.get_sink", boom)
        assert len(historian_push([{"metric": "0", "value": 1.0}], "tdengine")["error"]) <= 1000
