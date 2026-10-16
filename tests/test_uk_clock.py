"""UK civil clock (GMT/BST) without a tz database — the basis of half-hourly settlement days."""

from datetime import UTC, date, datetime, timedelta

import pytest

from iaiops.core.brain import uk_clock


@pytest.mark.unit
@pytest.mark.parametrize(
    ("day", "periods"),
    [
        (date(2026, 3, 29), 46),  # last Sunday of March 2026: clocks go forward
        (date(2026, 10, 25), 50),  # last Sunday of October 2026: clocks go back
        (date(2026, 3, 28), 48),
        (date(2026, 10, 26), 48),
        (date(2026, 7, 1), 48),
        (date(2025, 3, 30), 46),
        (date(2025, 10, 26), 50),
    ],
)
def test_periods_in_day(day, periods):
    assert uk_clock.periods_in_day(day) == periods


@pytest.mark.unit
def test_local_midnight_utc_in_winter_and_summer():
    assert uk_clock.local_midnight_utc(date(2026, 1, 15)) == datetime(2026, 1, 15, tzinfo=UTC)
    assert uk_clock.local_midnight_utc(date(2026, 7, 1)) == datetime(2026, 6, 30, 23, tzinfo=UTC)


@pytest.mark.unit
def test_to_local_crosses_the_spring_change():
    before = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)
    after = datetime(2026, 3, 29, 1, 0, tzinfo=UTC)
    assert uk_clock.to_local(before) == datetime(2026, 3, 29, 0, 30)
    assert uk_clock.to_local(after) == datetime(2026, 3, 29, 2, 0)


@pytest.mark.unit
def test_spring_gap_local_time_does_not_exist():
    assert uk_clock.local_to_utc(datetime(2026, 3, 29, 1, 30)) is None


@pytest.mark.unit
def test_autumn_repeated_hour_resolved_by_fold():
    first = uk_clock.local_to_utc(datetime(2026, 10, 25, 1, 30), fold=0)
    second = uk_clock.local_to_utc(datetime(2026, 10, 25, 1, 30), fold=1)
    assert first == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert second == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)


@pytest.mark.unit
def test_round_trip_every_half_hour_of_a_long_day():
    start = uk_clock.local_midnight_utc(date(2026, 10, 25))
    stamps = [start + timedelta(minutes=30 * i) for i in range(50)]
    assert uk_clock.local_midnight_utc(date(2026, 10, 26)) == stamps[-1] + timedelta(minutes=30)
    assert len({uk_clock.to_local(s) for s in stamps}) == 48  # the repeated hour folds


@pytest.mark.unit
def test_naive_utc_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        uk_clock.to_local(datetime(2026, 1, 1))
