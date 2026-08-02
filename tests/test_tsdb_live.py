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

import pytest

from iaiops.core.sink.reader import get_reader
from iaiops.core.sink.sqlite_local import SampleFilter

pytestmark = [pytest.mark.integration]

_HOST = "127.0.0.1"
_IOTDB_PORT = 6667
_TAOS_PORT = 6030


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

    sink = IoTDBSink(database=iotdb_database)
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

    reader = get_reader("iotdb", database=iotdb_database)
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

    sink = IoTDBSink(database=iotdb_database)
    sink.write(
        [
            {"metric": "old", "value": 1.0, "numeric": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"metric": "new", "value": 2.0, "numeric": True, "timestamp": "2026-06-01T00:00:00Z"},
        ]
    )
    sink.close()

    reader = get_reader("iotdb", database=iotdb_database)
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

    sink = IoTDBSink(database=iotdb_database)
    sink.write(
        [
            {"metric": "t1", "value": 1.0, "numeric": True, "timestamp": "2026-05-01T00:00:00Z"},
            {"metric": "t1", "value": 9.0, "numeric": True, "timestamp": "2026-05-02T00:00:00Z"},
            {"metric": "t2", "value": 5.0, "numeric": True, "timestamp": "2026-05-03T00:00:00Z"},
        ]
    )
    sink.close()

    reader = get_reader("iotdb", database=iotdb_database)
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


@needs_iotdb
def test_iotdb_reader_refuses_an_endpoint_filter(iotdb_database: str) -> None:
    """No endpoint label is stored — the reader must teach, not silently ignore.

    Silently dropping the filter would return every endpoint's data to someone
    who asked for one machine's, which on a plant floor is a wrong answer
    dressed as a right one.
    """
    reader = get_reader("iotdb", database=iotdb_database)
    try:
        with pytest.raises(ValueError, match="endpoint"):
            reader.query(SampleFilter(endpoint="plc-1", limit=10))
    finally:
        reader.close()


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
def test_tdengine_points_survive_the_ddl_and_come_back(tdengine_database: str) -> None:
    """Sink → real taosd → reader, including the `value` reserved-word DDL.

    `value` is a TDengine keyword: the CREATE STABLE fails outright without the
    back-quotes, and the reader's SELECT needs them too. That is exactly the
    class of defect a symbol check cannot see, and it is why this test exists
    rather than a mocked cursor.
    """
    _taos_or_skip()
    from iaiops.core.sink.tdengine import TDengineSink

    sink = TDengineSink(database=tdengine_database)
    written = sink.write(
        [
            {
                "metric": "line1.temperature",
                "value": 21.5,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:00.000",
            },
            # A second sample of the SAME metric, later: it is what makes
            # `latest()` and the coverage window falsifiable — with one point per
            # metric, "newest" and "oldest" are the same row and any ordering
            # mistake passes.
            {
                "metric": "line1.temperature",
                "value": 23.75,
                "numeric": True,
                "timestamp": "2026-08-02T00:05:00.000",
            },
            {
                "metric": "line1.pressure",
                "value": 4.25,
                "numeric": True,
                "timestamp": "2026-08-02T00:00:01.000",
            },
            {"metric": "line1.state", "value": "RUN", "numeric": False},
        ]
    )
    sink.close()
    assert written == 3, "the non-numeric point should not have been written"

    reader = get_reader("tdengine", database=tdengine_database)
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
    assert first["ts"].startswith("2026-08-02 00:00:00"), first

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
    assert temperature["first_ts"].startswith("2026-08-02 00:00:00"), coverage
    assert temperature["last_ts"].startswith("2026-08-02 00:05:00"), coverage


@needs_tdengine
def test_tdengine_time_bounds_narrow_on_the_server(tdengine_database: str) -> None:
    """`since`/`until` are pushed into the SQL — a real taosd applies them."""
    _taos_or_skip()
    from iaiops.core.sink.tdengine import TDengineSink

    sink = TDengineSink(database=tdengine_database)
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

    reader = get_reader("tdengine", database=tdengine_database)
    try:
        after_march = reader.query(SampleFilter(since="2026-03-01T00:00:00", limit=100))
        just_old = reader.query(SampleFilter(tag="old", limit=100))
    finally:
        reader.close()

    assert {r["tag"] for r in after_march} == {"new"}, after_march
    assert {r["tag"] for r in just_old} == {"old"}, just_old
