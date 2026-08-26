"""A timestamp that does not say which zone it is in is not a timestamp.

Found 2026-08-26 by pushing one cross-LAN collection run into BOTH lab
historians and reading it back. The same 999 samples, written by the same
command, came back as two different instants:

    IoTDB      2026-08-26T07:47:13.436000+00:00     ← ISO-8601, offset-aware
    TDengine   2026-08-26 15:47:13.436000           ← naive, client-LOCAL

Fed to this codebase's own ``parse_ts`` — which coerces a naive stamp to UTC, by
design and for good reasons — those land **28,800 seconds apart**. Same sample.

The server was never ambiguous. Asked over plain HTTP it answers
``2026-08-26T07:47:13.436Z``. The information is lost on OUR side of the wire:

* ``rest`` (taosrest) returns ``datetime(2026, 8, 26, 15, 47, 13, 436000)`` — the
  right instant converted into the CLIENT's local zone, with ``tzinfo`` dropped.
  Verified against the live lab server under TZ=UTC, Asia/Shanghai and
  America/New_York: the naive wall-clock moves with the client, and
  ``.astimezone()`` recovers the server's instant exactly in all three.
* ``websocket`` (taosws) returns the STRING ``'2026-08-26 15:47:13.436 +08:00'``
  — offset present, but with a space before it, which is not ISO-8601.
  ``datetime.fromisoformat`` rejects it and ``parse_ts`` returns ``None``.

So depending on which transport a site configured, the reader handed back a
timestamp that was either **silently eight hours wrong** or **unparseable**. The
live tests did not catch it because they assert on row COUNTS and values; nothing
compared a read-back stamp to the one that was written.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import pytest

from iaiops.core.brain._shared import parse_ts
from iaiops.core.sink.reader import _tsdb_ts_to_iso

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs TZ/tzset (POSIX)"),
]

#: The instant the lab server actually holds, as it reports it over plain HTTP.
INSTANT = datetime(2026, 8, 26, 7, 47, 13, 436000, tzinfo=UTC)
EXPECTED = "2026-08-26T07:47:13.436000+00:00"

CST = timezone(timedelta(hours=8))


def _as_client_local_naive(instant: datetime) -> datetime:
    """What taosrest hands back: the instant in THIS machine's zone, tzinfo gone.

    Built from the live clock rather than a hard-coded offset — a fixed -5 for
    "New York" is wrong in August (EDT is -4), and the first version of this file
    failed on exactly that, which is the same class of mistake the code under
    test makes.
    """
    return instant.astimezone().replace(tzinfo=None)


class TestEveryTransportsShapeBecomesTheSameInstant:
    """One instant in, one instant out — whatever the client handed us."""

    def test_an_aware_datetime_is_converted_not_relabelled(self):
        assert _tsdb_ts_to_iso(INSTANT.astimezone(CST)) == EXPECTED

    def test_a_naive_datetime_is_read_as_client_local(self, monkeypatch):
        """What `rest` returns. Naive here means "already converted to this
        machine's zone", NOT "UTC" — reading it as UTC is the eight-hour error."""
        with _local_zone("Asia/Shanghai"):
            # Built INSIDE the zone, exactly as taosrest builds it: the instant
            # converted to this machine's local time, then stripped of tzinfo.
            assert _tsdb_ts_to_iso(_as_client_local_naive(INSTANT)) == EXPECTED

    def test_the_same_naive_stamp_from_a_different_client_zone(self):
        """The complement that proves it is not hard-coded to +08:00: a laptop in
        New York gets a different wall-clock for the same instant, and must still
        resolve to the same instant."""
        with _local_zone("America/New_York"):
            naive = _as_client_local_naive(INSTANT)
            assert naive.hour != INSTANT.hour, "the fixture must actually move the clock"
            assert _tsdb_ts_to_iso(naive) == EXPECTED

    def test_the_websocket_string_with_its_space_before_the_offset(self):
        """Verbatim from taosws against the live lab server."""
        assert _tsdb_ts_to_iso("2026-08-26 15:47:13.436 +08:00") == (
            "2026-08-26T07:47:13.436000+00:00"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "2026-08-26T07:47:13.436Z",
            "2026-08-26T07:47:13.436+00:00",
            "2026-08-26 07:47:13.436000+00:00",
        ],
        ids=["zulu", "offset", "space-separator"],
    )
    def test_an_already_unambiguous_string_survives_unchanged_in_meaning(self, text):
        assert parse_ts(_tsdb_ts_to_iso(text)) == INSTANT


class TestItIsAlwaysParseableByOurOwnParser:
    """The property that actually matters downstream. `parse_ts` returning None
    is how a window quietly contains nothing."""

    @pytest.mark.parametrize(
        "value",
        [
            INSTANT,
            INSTANT.astimezone(CST),
            "2026-08-26 15:47:13.436 +08:00",
            "2026-08-26T07:47:13.436Z",
        ],
        ids=["utc-datetime", "aware-datetime", "taosws-string", "zulu-string"],
    )
    def test_round_tripping_through_the_reader_lands_on_the_instant(self, value):
        assert parse_ts(_tsdb_ts_to_iso(value)) == INSTANT


class TestItRefusesRatherThanInvents:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_nothing_becomes_an_empty_string(self, value):
        assert _tsdb_ts_to_iso(value) == ""

    def test_an_unrecognisable_stamp_is_passed_through_not_guessed(self):
        """A shape no client here produces. Inventing an instant for it would be
        worse than handing back what arrived: the operator can see the latter is
        wrong, and cannot see the former."""
        assert _tsdb_ts_to_iso("last Tuesday") == "last Tuesday"

    def test_it_stays_bounded(self):
        assert len(_tsdb_ts_to_iso("x" * 5_000)) <= 40


class TestTheReaderUsesIt:
    """The helper being correct is not the fix; the reader calling it is."""

    def test_query_rows_carry_a_normalized_stamp(self, monkeypatch):
        from iaiops.core.sink.reader import TDengineReader
        from iaiops.core.sink.sqlite_local import SampleFilter

        reader = TDengineReader(host="10.0.0.5", database="db", transport="rest")
        with _local_zone("Asia/Shanghai"):
            naive = _as_client_local_naive(INSTANT)
            monkeypatch.setattr(reader, "_run", lambda sql: [(naive, 2.0, "0")])
            rows = reader.query(SampleFilter(limit=10))
        assert rows[0]["ts"] == EXPECTED

    def test_coverage_bounds_carry_a_normalized_stamp(self, monkeypatch):
        from iaiops.core.sink.reader import TDengineReader

        reader = TDengineReader(host="10.0.0.5", database="db", transport="rest")
        with _local_zone("Asia/Shanghai"):
            naive = _as_client_local_naive(INSTANT)
            monkeypatch.setattr(reader, "_run", lambda sql: [("0", 333, naive, naive)])
            rows = reader.coverage()
        assert rows[0]["first_ts"] == EXPECTED and rows[0]["last_ts"] == EXPECTED

    def test_latest_rows_carry_a_normalized_stamp(self, monkeypatch):
        from iaiops.core.sink.reader import TDengineReader

        reader = TDengineReader(host="10.0.0.5", database="db", transport="rest")
        monkeypatch.setattr(
            reader, "_run", lambda sql: [("2026-08-26 15:47:13.436 +08:00", 2.0, "0")]
        )
        assert reader.latest()[0]["ts"] == EXPECTED

    def test_it_agrees_with_the_iotdb_reader(self):
        """The assertion the whole file is for: two readers, one format. A fix
        that made TDengine self-consistent but still different from IoTDB would
        leave the cross-historian comparison exactly as broken."""
        from iaiops.core.sink.reader import _millis_to_iso

        iotdb_shape = _millis_to_iso(INSTANT.timestamp() * 1000)
        assert parse_ts(iotdb_shape) == parse_ts(_tsdb_ts_to_iso(INSTANT))


@contextmanager
def _local_zone(name: str):
    """Run a block as if this machine were in ``name``.

    The whole naive branch turns on what the PLATFORM thinks local time is, so
    the test has to move the platform rather than the code — patching
    ``datetime.astimezone`` is not possible (a C type) and patching the helper
    would test the mock. ``TZ`` + ``tzset`` is what actually reaches
    ``astimezone()``; verified by watching one naive wall-clock resolve to three
    different instants under three zones.
    """
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
