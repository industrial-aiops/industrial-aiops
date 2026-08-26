"""Historian TSDBs against REAL servers — IoTDB and TDengine round-trips.

Until now these two sinks sat at **rung 1**: `test_binding_contracts.py` asserts
that `iotdb.Session` has the methods we call and that `taos.connect` exists. A
symbol check cannot see a wrong path shape, a reserved word, a timestamp unit or
a `LAST` result whose columns are not where the parser looks — and both readers
(`iaiops/core/sink/reader.py`) are pages of hand-written SQL plus hand-written
result parsing that no server had ever judged.

Both sinks' module docstrings claimed a live round-trip "verified 2026-06-30".
That claim was true of a session that no longer exists and that nothing could
reproduce, which is the kind of claim `docs/VERIFICATION-RECORD.md` exists to
outlaw. This file makes it reproducible: a real server writes what the sink
sends and answers what the reader asks, so **rung 2a** — a third-party
implementation judges our statements in both directions.

Start the servers::

    docker run -d --rm --name iaiops-iotdb -p 6667:6667 apache/iotdb:1.3.2-standalone
    docker run -d --rm --name iaiops-taos -p 6030:6030 tdengine/tdengine:3.3.5.0

TDengine additionally needs the native client (`libtaos`) on the loader path —
it is a vendor tarball, not a PyPI wheel — so its tests skip where the import
fails rather than pretending the sink was checked. IoTDB's client is a pure
thrift wheel and needs nothing but `pip install iaiops[iotdb]`.
"""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from iaiops.core.brain._shared import parse_ts
from iaiops.core.sink.reader import get_reader
from iaiops.core.sink.sqlite_local import SampleFilter

pytestmark = [pytest.mark.integration]

#: Where the historian servers are. Defaults to localhost, but a lab server on
#: another machine is an ordinary setup — and hardcoding loopback meant these
#: tests could only ever run somewhere Docker also runs, which is exactly the
#: machine least likely to be free to host a TSDB. `IAIOPS_TSDB_HOST=10.0.0.5`
#: points them at a real one; the skip messages name it so a failure to reach it
#: reads as "wrong host", not "no server".
_HOST = os.environ.get("IAIOPS_TSDB_HOST", "127.0.0.1")
_IOTDB_PORT = 6667
_TAOS_PORT = 6030
_TAOS_ADAPTER_PORT = 6041  # taosAdapter: REST and WebSocket share this port


def _reachable(port: int) -> bool:
    try:
        with socket.create_connection((_HOST, port), timeout=1.0):
            return True
    except OSError:
        return False


needs_iotdb = pytest.mark.skipif(
    not _reachable(_IOTDB_PORT),
    reason=(
        f"no IoTDB at {_HOST}:{_IOTDB_PORT} "
        "(docker run -d -p 6667:6667 apache/iotdb:1.3.2-standalone)"
    ),
)

needs_tdengine = pytest.mark.skipif(
    not _reachable(_TAOS_PORT),
    reason=(
        f"no TDengine at {_HOST}:{_TAOS_PORT} "
        "(docker run -d -p 6030:6030 tdengine/tdengine:3.3.5.0)"
    ),
)


def _unique(prefix: str) -> str:
    """A per-run identifier so a rerun never reads the previous run's rows.

    Both servers persist across tests in a session and across sessions in a
    container, so a fixed database name would let stale rows satisfy assertions
    that the code under test no longer earns.
    """
    return f"{prefix}{os.getpid()}_{int(time.monotonic() * 1000) % 1_000_000}"


# ─── Apache IoTDB ────────────────────────────────────────────────────────────


@pytest.fixture
def iotdb_database() -> Iterator[str]:
    """A throwaway IoTDB database, deleted afterwards."""
    pytest.importorskip("iotdb", reason="apache-iotdb not installed — install iaiops[iotdb]")
    database = f"root.{_unique('iaiops_test_')}"
    yield database
    from iotdb.Session import Session

    session = Session(_HOST, _IOTDB_PORT, "root", "root")
    session.open(False)
    try:
        # A test that wrote nothing never created the database (IoTDB creates it
        # on first insert) and 1.3 has no `DELETE DATABASE IF EXISTS`, so a
        # missing path raises. Cleanup must not turn a passing test into an
        # erroring one — but only that one error is swallowed.
        session.execute_non_query_statement(f"DELETE DATABASE {database}")
    except Exception as exc:  # noqa: BLE001 — StatementExecutionException 508
        if "does not exist" not in str(exc):
            raise
    finally:
        session.close()


@needs_iotdb
def test_iotdb_points_land_on_the_path_the_reader_looks_under(iotdb_database: str) -> None:
    """Write through the sink, read back through the reader, against a real server.

    The two halves are written against the same idea of the path
    (``<database>.<sanitized metric>.value``) — but a real IoTDB is what decides
    whether that path is legal, whether the DOUBLE type is accepted and whether
    the epoch-millis timestamp means what the sink thinks. An in-process fake
    would agree with us about all three.
    """
    from iaiops.core.sink.iotdb import IoTDBSink

    sink = IoTDBSink(host=_HOST, database=iotdb_database)
    written = sink.write(
        [
            {
                "metric": "line1.temperature",
                "value": 21.5,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:00Z",
            },
            {
                "metric": "line1.pressure",
                "value": 4.25,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:01Z",
            },
            # Non-numeric points have no home in a DOUBLE timeseries; the sink
            # skips them rather than coercing a state string to a number.
            {"metric": "line1.state", "value": "RUN", "numeric": False},
        ]
    )
    sink.close()
    assert written == 2, "the non-numeric point should not have been written"

    reader = get_reader("iotdb", host=_HOST, database=iotdb_database)
    try:
        rows = reader.query(SampleFilter(limit=100))
    finally:
        reader.close()

    by_tag = {row["tag"]: row for row in rows}
    assert set(by_tag) == {"line1_temperature", "line1_pressure"}, (
        f"the reader did not find what the sink wrote: {rows}"
    )
    assert by_tag["line1_temperature"]["value"] == pytest.approx(21.5)
    assert by_tag["line1_pressure"]["value"] == pytest.approx(4.25)
    # The ISO→millis→ISO round-trip: a naive or mis-scaled timestamp would show
    # up here as 1970, as local time, or as 56 thousand years from now.
    assert by_tag["line1_temperature"]["ts"].startswith("2026-08-02T00:00:00"), (
        f"timestamp did not survive the round-trip: {by_tag['line1_temperature']['ts']}"
    )


@needs_iotdb
def test_iotdb_serves_a_modbus_line_whose_tags_are_register_numbers(
    iotdb_database: str,
) -> None:
    """A bare number is not a legal IoTDB path node — and Modbus tags ARE numbers.

    `collect run` against a Modbus endpoint stores its samples under the register
    address, so a plain line yields the tags `0` and `10`. Unquoted, the server
    refuses BOTH directions — `ILLEGAL_PATH(509)` on insert and "no viable
    alternative at input" on select — so an IoTDB historian could not serve a
    Modbus site at all. Nothing caught it because every fixture in this file uses
    alphabetic metric names, which happen to be legal unquoted.

    Only a real server can answer this: the node grammar is IoTDB's, not ours.
    """
    from iaiops.core.sink.iotdb import IoTDBSink

    sink = IoTDBSink(host=_HOST, database=iotdb_database)
    written = sink.write(
        [
            {"metric": "0", "value": 2.0, "numeric": True, "timestamp": "2026-08-02T00:00:00Z"},
            {"metric": "10", "value": 41.0, "numeric": True, "timestamp": "2026-08-02T00:00:01Z"},
        ]
    )
    sink.close()
    assert written == 2

    reader = get_reader("iotdb", host=_HOST, database=iotdb_database)
    try:
        rows = reader.query(SampleFilter(limit=100))
        one_tag = reader.query(SampleFilter(tag="0", limit=100))
        cover = reader.coverage(limit=100)
    finally:
        reader.close()

    # The tag comes back as the operator wrote it — a stray backtick here would
    # mean no downstream lookup by tag name could ever match.
    assert {row["tag"] for row in rows} == {"0", "10"}, rows
    assert [row["value"] for row in one_tag] == [pytest.approx(2.0)], one_tag
    assert {row["tag"] for row in cover} == {"0", "10"}, cover


@needs_iotdb
def test_iotdb_quoting_does_not_move_an_existing_series(iotdb_database: str) -> None:
    """A backquoted node and its bare form must be the SAME node.

    The fix quotes every path node, including the alphabetic ones already stored
    by earlier versions. If the server treated `` `T` `` as a different node from
    `T`, every existing historian would silently appear empty after an upgrade —
    a far worse outcome than the bug being fixed. Written unquoted, read quoted.
    """
    from iotdb.Session import Session
    from iotdb.utils.IoTDBConstants import TSDataType

    session = Session(_HOST, _IOTDB_PORT, "root", "root")
    session.open(False)
    try:
        # Deliberately NOT through the sink: this must be the pre-fix on-disk form.
        session.insert_record(
            f"{iotdb_database}.LEGACY_TAG", 1_785_628_800_000, ["value"], [TSDataType.DOUBLE], [7.5]
        )
    finally:
        session.close()

    reader = get_reader("iotdb", host=_HOST, database=iotdb_database)
    try:
        rows = reader.query(SampleFilter(tag="LEGACY_TAG", limit=10))
    finally:
        reader.close()

    assert [row["value"] for row in rows] == [pytest.approx(7.5)], (
        f"quoting moved an existing series — every stored historian would read empty: {rows}"
    )


@needs_iotdb
def test_iotdb_time_bounds_and_tag_filter_are_applied_by_the_server(
    iotdb_database: str,
) -> None:
    """`since`/`until`/`tag` must narrow the result **on the server**.

    The reader converts bounds to epoch-millis and interpolates them into the
    SQL. If the conversion or the column name (`time`, not `ts`) were wrong, an
    unfiltered result would still look like a pass to a test that only counted
    rows — so each assertion names the row that must survive and the row that
    must not.
    """
    from iaiops.core.sink.iotdb import IoTDBSink

    sink = IoTDBSink(host=_HOST, database=iotdb_database)
    sink.write(
        [
            {"metric": "old", "value": 1.0, "numeric": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"metric": "new", "value": 2.0, "numeric": True, "timestamp": "2026-06-01T00:00:00Z"},
        ]
    )
    sink.close()

    reader = get_reader("iotdb", host=_HOST, database=iotdb_database)
    try:
        after_march = reader.query(SampleFilter(since="2026-03-01T00:00:00Z", limit=100))
        before_march = reader.query(SampleFilter(until="2026-03-01T00:00:00Z", limit=100))
        just_old = reader.query(SampleFilter(tag="old", limit=100))
    finally:
        reader.close()

    assert {r["tag"] for r in after_march} == {"new"}, after_march
    assert {r["tag"] for r in before_march} == {"old"}, before_march
    assert {r["tag"] for r in just_old} == {"old"}, just_old


@needs_iotdb
def test_iotdb_latest_and_coverage_parse_a_real_result_set(iotdb_database: str) -> None:
    """`latest()` and `coverage()` parse IoTDB's own column names, not ours.

    These are the two queries whose result *shape* is invented in this repo: the
    `LAST` query's `Time | timeseries | value | dataType` layout and the
    `COUNT(root.db.tag.value)` aggregate column that `_parse_aggregate_column`
    takes apart with string surgery. Nothing but a real server produces either.
    """
    from iaiops.core.sink.iotdb import IoTDBSink

    sink = IoTDBSink(host=_HOST, database=iotdb_database)
    sink.write(
        [
            {"metric": "t1", "value": 1.0, "numeric": True, "timestamp": "2026-05-01T00:00:00Z"},
            {"metric": "t1", "value": 9.0, "numeric": True, "timestamp": "2026-05-02T00:00:00Z"},
            {"metric": "t2", "value": 5.0, "numeric": True, "timestamp": "2026-05-03T00:00:00Z"},
        ]
    )
    sink.close()

    reader = get_reader("iotdb", host=_HOST, database=iotdb_database)
    try:
        latest = reader.latest(limit=10)
        coverage = reader.coverage(limit=10)
    finally:
        reader.close()

    latest_by_tag = {row["tag"]: row for row in latest}
    assert set(latest_by_tag) == {"t1", "t2"}, f"LAST result parsed wrong: {latest}"
    # 9.0, not 1.0 — proves the row chosen is the newest, i.e. that the value
    # column was read from the right field of the LAST layout.
    assert latest_by_tag["t1"]["value"] == pytest.approx(9.0), latest

    coverage_by_tag = {row["tag"]: row for row in coverage}
    assert set(coverage_by_tag) == {"t1", "t2"}, f"aggregate columns parsed wrong: {coverage}"
    assert coverage_by_tag["t1"]["rows"] == 2, coverage
    assert coverage_by_tag["t1"]["first_ts"].startswith("2026-05-01"), coverage
    assert coverage_by_tag["t1"]["last_ts"].startswith("2026-05-02"), coverage


# ─── TDengine ────────────────────────────────────────────────────────────────


def _taos_or_skip():
    """Import the native `taos` module, or skip with the honest reason.

    `taos` dlopen()s libtaos at IMPORT time, so "taospy installed" and "the
    TDengine sink can run" are different facts; the skip reason says which one
    is missing.
    """
    try:
        import taos
    except ImportError:
        pytest.skip("taospy not installed — install iaiops[tdengine]")
    except Exception as exc:  # noqa: BLE001 — InterfaceError: libtaos absent
        pytest.skip(f"libtaos client library not loadable: {exc}")
    return taos


@pytest.fixture
def tdengine_database() -> Iterator[str]:
    """A throwaway TDengine database, dropped afterwards."""
    taos = _taos_or_skip()
    database = _unique("iaiops_test_")
    yield database
    connection = taos.connect(host=_HOST, port=_TAOS_PORT, user="root", password="taosdata")
    try:
        connection.cursor().execute(f"DROP DATABASE IF EXISTS {database}")
    finally:
        connection.close()


@needs_tdengine
@pytest.mark.optional_live
def test_tdengine_points_survive_the_ddl_and_come_back(tdengine_database: str) -> None:
    """Sink → real taosd → reader, including the `value` reserved-word DDL.

    `value` is a TDengine keyword: the CREATE STABLE fails outright without the
    back-quotes, and the reader's SELECT needs them too. That is exactly the
    class of defect a symbol check cannot see, and it is why this test exists
    rather than a mocked cursor.
    """
    _taos_or_skip()
    from iaiops.core.sink.tdengine import TDengineSink

    sink = TDengineSink(host=_HOST, database=tdengine_database)
    written = sink.write(
        [
            {
                "metric": "line1.temperature",
                "value": 21.5,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:00.000Z",
            },
            # A second sample of the SAME metric, later: it is what makes
            # `latest()` and the coverage window falsifiable — with one point per
            # metric, "newest" and "oldest" are the same row and any ordering
            # mistake passes.
            {
                "metric": "line1.temperature",
                "value": 23.75,
                "numeric": True,
                "timestamp": "2026-08-02T00:05:00.000Z",
            },
            {
                "metric": "line1.pressure",
                "value": 4.25,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:01.000Z",
            },
            {"metric": "line1.state", "value": "RUN", "numeric": False},
        ]
    )
    sink.close()
    assert written == 3, "the non-numeric point should not have been written"

    reader = get_reader("tdengine", host=_HOST, database=tdengine_database)
    try:
        rows = reader.query(SampleFilter(limit=100))
        latest = reader.latest(limit=10)
        coverage = reader.coverage(limit=10)
    finally:
        reader.close()

    # The tag carries the ORIGINAL metric (the sub-table name is sanitized, the
    # tag is not) — so a caller gets back the name they pushed.
    assert [row["tag"] for row in rows] == [
        "line1.temperature",
        "line1.pressure",
        "line1.temperature",
    ], f"ORDER BY ts did not hold, or tags were misattributed: {rows}"
    first = rows[0]
    assert first["value"] == pytest.approx(21.5)
    # The instant that was WRITTEN, not a string shape. Until 2026-08-26 this
    # asserted `"2026-08-02 00:00:00"` — the naive, client-LOCAL text the reader
    # forwarded straight from the client — and so it pinned the defect instead of
    # catching it: the same row read on a UTC+8 laptop said 08:00 and this test,
    # running on a UTC runner, never saw it. Comparing instants is what makes the
    # assertion independent of where it runs.
    assert parse_ts(first["ts"]) == datetime(2026, 8, 2, tzinfo=UTC), first

    latest_by_tag = {row["tag"]: row for row in latest}
    assert set(latest_by_tag) == {"line1.temperature", "line1.pressure"}, latest
    # 23.75, not 21.5 — LAST(ts)/LAST(`value`) must pick the newer sample.
    assert latest_by_tag["line1.temperature"]["value"] == pytest.approx(23.75), latest

    coverage_by_tag = {row["tag"]: row for row in coverage}
    temperature = coverage_by_tag["line1.temperature"]
    assert temperature["rows"] == 2, coverage
    # FIRST(ts) before LAST(ts): a swapped pair would report the window backwards,
    # which is how a caller decides there is no data for their incident.
    assert temperature["first_ts"] < temperature["last_ts"], coverage
    assert parse_ts(temperature["first_ts"]) == datetime(2026, 8, 2, tzinfo=UTC), coverage
    assert parse_ts(temperature["last_ts"]) == datetime(2026, 8, 2, 0, 5, tzinfo=UTC), coverage


@needs_tdengine
@pytest.mark.optional_live
def test_tdengine_time_bounds_narrow_on_the_server(tdengine_database: str) -> None:
    """`since`/`until` are pushed into the SQL — a real taosd applies them."""
    _taos_or_skip()
    from iaiops.core.sink.tdengine import TDengineSink

    sink = TDengineSink(host=_HOST, database=tdengine_database)
    sink.write(
        [
            {
                "metric": "old",
                "value": 1.0,
                "numeric": True,
                "timestamp": "2026-01-01T00:00:00.000",
            },
            {
                "metric": "new",
                "value": 2.0,
                "numeric": True,
                "timestamp": "2026-06-01T00:00:00.000",
            },
        ]
    )
    sink.close()

    reader = get_reader("tdengine", host=_HOST, database=tdengine_database)
    try:
        after_march = reader.query(SampleFilter(since="2026-03-01T00:00:00", limit=100))
        # `until` builds a second clause in the same SQL and had never reached a
        # real taosd — in the dialect where the live round-trip already found that
        # MIN()/MAX() on a TIMESTAMP is rejected outright, an unexercised bound is
        # not a safe assumption.
        before_march = reader.query(SampleFilter(until="2026-03-01T00:00:00", limit=100))
        just_old = reader.query(SampleFilter(tag="old", limit=100))
    finally:
        reader.close()

    assert {r["tag"] for r in after_march} == {"new"}, after_march
    assert {r["tag"] for r in before_march} == {"old"}, before_march
    assert {r["tag"] for r in just_old} == {"old"}, just_old


@needs_iotdb
def test_iotdb_newest_first_keeps_the_end_nearest_the_incident(iotdb_database: str) -> None:
    """`newest_first` has to be pushed into the SERVER's ORDER BY, not faked here.

    A reader that fetched the oldest rows and reversed them in Python would pass
    any assertion about ORDER but return the wrong five samples. The values are
    positional, so which five came back is the whole test.
    """
    from iaiops.core.sink.iotdb import IoTDBSink

    sink = IoTDBSink(host=_HOST, database=iotdb_database)
    sink.write(
        [
            {
                "metric": "t1",
                "value": float(i),
                "numeric": True,
                "timestamp": f"2026-05-01T00:{i:02d}:00Z",
            }
            for i in range(20)
        ]
    )
    sink.close()

    reader = get_reader("iotdb", host=_HOST, database=iotdb_database)
    try:
        oldest = reader.query(SampleFilter(tag="t1", limit=5))
        newest = reader.query(SampleFilter(tag="t1", limit=5, newest_first=True))
    finally:
        reader.close()

    assert [row["value"] for row in oldest] == [0.0, 1.0, 2.0, 3.0, 4.0], oldest
    assert [row["value"] for row in newest] == [15.0, 16.0, 17.0, 18.0, 19.0], newest
    assert [row["ts"] for row in newest] == sorted(row["ts"] for row in newest)


@needs_tdengine
@pytest.mark.optional_live
def test_tdengine_newest_first_keeps_the_end_nearest_the_incident(
    tdengine_database: str,
) -> None:
    """The same push-down, in the dialect where an unexercised clause already bit."""
    _taos_or_skip()
    from iaiops.core.sink.tdengine import TDengineSink

    sink = TDengineSink(host=_HOST, database=tdengine_database)
    sink.write(
        [
            {
                "metric": "t1",
                "value": float(i),
                "numeric": True,
                "timestamp": f"2026-05-01T00:{i:02d}:00.000",
            }
            for i in range(20)
        ]
    )
    sink.close()

    reader = get_reader("tdengine", host=_HOST, database=tdengine_database)
    try:
        oldest = reader.query(SampleFilter(tag="t1", limit=5))
        newest = reader.query(SampleFilter(tag="t1", limit=5, newest_first=True))
    finally:
        reader.close()

    assert [row["value"] for row in oldest] == [0.0, 1.0, 2.0, 3.0, 4.0], oldest
    assert [row["value"] for row in newest] == [15.0, 16.0, 17.0, 18.0, 19.0], newest
    assert [row["ts"] for row in newest] == sorted(row["ts"] for row in newest)


# ─── TDengine transports: the same assertions over native / REST / WebSocket ──


def _transport_available(transport: str) -> bool:
    """Is this transport's client importable here?"""
    try:
        if transport == "native":
            import taos  # noqa: F401
        elif transport == "rest":
            import taosrest  # noqa: F401
        else:
            import taosws  # noqa: F401
    except Exception:  # noqa: BLE001 — the native one raises at import without libtaos
        return False
    return True


@pytest.mark.parametrize("transport", ["rest", "websocket"])
def test_tdengine_round_trip_over_a_libtaos_free_transport(transport: str, tmp_path) -> None:
    """The whole write→read path, without the native client at all.

    This is the point of the transports: `libtaos` is a vendor download that is
    not on PyPI, so the native client is unusable on any machine that has not
    installed it out of band — every macOS box here, and CI only manages it by
    fetching a sha256-pinned tarball. REST and WebSocket need no native library,
    and taosAdapter serves both on 6041.

    The assertions are deliberately the same ones the native test makes: if a
    transport is a real alternative, it has to answer identically, DDL and
    reserved word and all.
    """
    if not _reachable(_TAOS_ADAPTER_PORT):
        pytest.skip(f"no taosAdapter at {_HOST}:{_TAOS_ADAPTER_PORT} (publish -p 6041:6041)")
    if not _transport_available(transport):
        pytest.skip(f"the {transport} client is not installed")

    from iaiops.core.sink.tdengine import TDengineSink

    database = _unique("iaiops_tr_")
    sink = TDengineSink(host=_HOST, database=database, transport=transport)
    written = sink.write(
        [
            {
                "metric": "line1.temperature",
                "value": 21.5,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:00.000",
            },
            {
                "metric": "line1.temperature",
                "value": 23.75,
                "numeric": True,
                "timestamp": "2026-08-02T00:05:00.000",
            },
            {"metric": "line1.state", "value": "RUN", "numeric": False},
        ]
    )
    sink.close()
    assert written == 2, "the non-numeric point should not have been written"

    reader = get_reader("tdengine", host=_HOST, database=database, transport=transport)
    try:
        rows = reader.query(SampleFilter(limit=100))
        newest = reader.query(SampleFilter(limit=1, newest_first=True))
        coverage = reader.coverage(limit=10)
    finally:
        reader.close()

    assert [row["tag"] for row in rows] == ["line1.temperature", "line1.temperature"], rows
    assert rows[0]["value"] == pytest.approx(21.5)
    # newest_first has to be pushed into this transport's SQL too.
    assert newest[0]["value"] == pytest.approx(23.75), newest
    by_tag = {row["tag"]: row for row in coverage}
    assert by_tag["line1.temperature"]["rows"] == 2, coverage
