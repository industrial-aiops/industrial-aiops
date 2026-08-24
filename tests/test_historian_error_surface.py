"""A historian failure must reach the operator as one line, not 111 of traceback.

Two defects, both found on 2026-08-24 by pointing a `config.yaml` at a live
Apache IoTDB and running `iaiops historian coverage` — the path a customer
actually takes. Every existing test either mocks the reader or constructs it
directly with keyword arguments, so neither could show:

1. `HistorianConfig`'s own docstring documented `database: iaiops` for IoTDB.
   No IoTDB path is valid without the `root.` prefix, so following our
   documentation produced a server-side SQL parse error naming OUR generated
   statement — which says nothing about the line the operator typed.

2. The TSDB client libraries raise their own exception types (taospy's
   `ProgrammingError`, IoTDB's thrift `StatementExecutionException`). Neither is
   a `ValueError` or an `OSError`, so nothing in the CLI's error harness
   recognised them and every historian failure — unreachable server, wrong
   password, dropped database — escaped as a raw traceback with our SQL in it.
"""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from iaiops.core.runtime.config import HistorianConfig
from iaiops.core.sink.base import SinkError
from iaiops.core.sink.reader import IoTDBReader, TDengineReader, _client_errors
from iaiops.core.sink.sqlite_local import SampleFilter

pytestmark = pytest.mark.unit


class _ForeignClientError(Exception):
    """Stands in for a client library's own exception type — ours knows nothing of it."""


class TestTheIoTDBDatabaseMustBeAnIoTDBPath:
    def test_a_bare_name_is_refused(self):
        with pytest.raises(ValueError) as excinfo:
            HistorianConfig(reader="iotdb", host="h", database="iaiops")
        assert "root.iaiops" in str(excinfo.value)

    def test_the_message_names_the_field_and_the_fix(self):
        """The operator is holding a config file — point at the line, not at SQL."""
        with pytest.raises(ValueError) as excinfo:
            HistorianConfig(reader="iotdb", host="h", database="plant_a")
        message = str(excinfo.value)
        assert "historian.database" in message
        assert "root.plant_a" in message

    def test_a_rooted_path_is_accepted(self):
        assert HistorianConfig(reader="iotdb", database="root.iaiops").database == "root.iaiops"

    def test_a_deeper_rooted_path_is_accepted(self):
        """`root.site.line1` is as legitimate as `root.iaiops`; only the prefix is required."""
        assert HistorianConfig(reader="iotdb", database="root.site.line1").database

    def test_an_absent_database_still_takes_the_readers_default(self):
        """Existing configs that omit it are unchanged — the rule is about wrong, not missing."""
        assert HistorianConfig(reader="iotdb", host="h").database == ""

    @pytest.mark.parametrize("reader", ["tdengine", "sqlite"])
    def test_the_rule_does_not_leak_to_the_other_readers(self, reader):
        """`iaiops` is the correct TDengine database name; refusing it would be a
        new bug wearing the fix's clothes."""
        assert HistorianConfig(reader=reader, database="iaiops").database == "iaiops"


class TestForeignClientErrorsBecomeTeachingErrors:
    def test_an_unknown_exception_becomes_a_sink_error(self):
        with pytest.raises(SinkError) as excinfo:
            with _client_errors("iotdb", "run the query"):
                raise _ForeignClientError("700: no viable alternative at input")
        assert "iotdb" in str(excinfo.value)
        assert "no viable alternative" in str(excinfo.value)

    def test_our_own_errors_pass_through_unwrapped(self):
        """A `ValueError` already carries a written message; re-wrapping buries it."""
        with pytest.raises(ValueError) as excinfo:
            with _client_errors("iotdb", "run the query"):
                raise ValueError("limit must be 1..10000 (got 0).")
        assert not isinstance(excinfo.value, SinkError)
        assert "limit must be" in str(excinfo.value)

    def test_a_sink_error_is_not_double_wrapped(self):
        with pytest.raises(SinkError) as excinfo:
            with _client_errors("iotdb", "run the query"):
                raise SinkError("The 'apache-iotdb' package is not installed.")
        assert "failed to run the query" not in str(excinfo.value)


class _ExplodingSession:
    """An IoTDB session whose every statement raises the library's own type."""

    def execute_query_statement(self, sql: str):
        raise _ForeignClientError("700: Error occurred while parsing SQL to physical plan")

    def close(self) -> None:
        pass


class _ExplodingCursor:
    def execute(self, sql: str):
        raise _ForeignClientError("[0x2802]: Invalid parameter data type")

    def fetchall(self):  # pragma: no cover — execute raises first
        return []


class _ExplodingConn:
    def cursor(self):
        return _ExplodingCursor()

    def close(self) -> None:
        pass


def _iotdb() -> IoTDBReader:
    reader = IoTDBReader(host="h", database="root.iaiops")
    reader._session = _ExplodingSession()
    return reader


def _tdengine() -> TDengineReader:
    reader = TDengineReader(host="h", transport="rest")
    reader._conn = _ExplodingConn()
    return reader


class TestEveryReadPathIsCovered:
    """A wrapper on one method is a wrapper the next incident routes around."""

    @pytest.mark.parametrize("build", [_iotdb, _tdengine], ids=["iotdb", "tdengine"])
    def test_query(self, build):
        with pytest.raises(SinkError):
            build().query(SampleFilter(tag="BEARING_TEMP", limit=10))

    @pytest.mark.parametrize("build", [_iotdb, _tdengine], ids=["iotdb", "tdengine"])
    def test_latest(self, build):
        with pytest.raises(SinkError):
            build().latest(limit=10)

    @pytest.mark.parametrize("build", [_iotdb, _tdengine], ids=["iotdb", "tdengine"])
    def test_coverage(self, build):
        with pytest.raises(SinkError):
            build().coverage(limit=10)

    def test_a_bad_limit_is_still_a_value_error_not_a_sink_error(self):
        """The wrapper must not swallow the boundary validation it surrounds."""
        with pytest.raises(ValueError) as excinfo:
            _iotdb().coverage(limit=0)
        assert not isinstance(excinfo.value, SinkError)


class TestTheCliShowsOneLine:
    def test_a_sink_error_is_a_teaching_line_and_exit_1(self):
        from iaiops.cli._common import cli_errors

        app = typer.Typer()

        @app.command()
        @cli_errors
        def boom() -> None:
            raise SinkError("The iotdb historian failed to connect to h:6667.")

        result = CliRunner().invoke(app, [])
        assert result.exit_code == 1
        assert "failed to connect to h:6667" in result.output
        assert "Traceback" not in result.output
