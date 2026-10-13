"""The UK civil clock (GMT / BST), computed from the rule rather than a tz database.

Half-hourly settlement is defined on the LOCAL day: a settlement day runs from
local midnight to local midnight, so it has 46 periods on the day the clocks go
forward, 50 on the day they go back, and 48 otherwise. Every supplier file is laid
out that way, so reading one correctly needs the clock rule — and only the UK one.

Why not ``zoneinfo``: on Windows it needs the third-party ``tzdata`` package, and
this package installs without it. The rule has been fixed since 1998 (EU summer
time, retained in UK law): BST runs from **01:00 UTC on the last Sunday of March**
to **01:00 UTC on the last Sunday of October**. If Parliament ever changes it this
module is the one place to edit, and the tests pin the dates it must produce.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

_HALF_HOUR = timedelta(minutes=30)
_BST = timedelta(hours=1)
_GMT = timedelta(0)


def _last_sunday(year: int, month: int) -> date:
    """Last Sunday of ``month`` (March or October — both have 31 days)."""
    last = date(year, month, 31)
    return last - timedelta(days=(last.weekday() - 6) % 7)


def bst_bounds(year: int) -> tuple[datetime, datetime]:
    """The UTC instants BST starts and ends in ``year``."""
    start = datetime.combine(_last_sunday(year, 3), datetime.min.time(), UTC) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(year, 10), datetime.min.time(), UTC) + timedelta(hours=1)
    return start, end


def utc_offset(instant: datetime) -> timedelta:
    """Offset of UK local time from UTC at ``instant`` (aware)."""
    if instant.tzinfo is None:
        raise ValueError("utc_offset needs a timezone-aware instant")
    utc = instant.astimezone(UTC)
    start, end = bst_bounds(utc.year)
    return _BST if start <= utc < end else _GMT


def to_local(instant: datetime) -> datetime:
    """UK local wall-clock time (naive) for an aware instant."""
    if instant.tzinfo is None:
        raise ValueError("to_local needs a timezone-aware instant, got a naive one")
    utc = instant.astimezone(UTC)
    return (utc + utc_offset(utc)).replace(tzinfo=None)


def local_to_utc(local: datetime, fold: int = 0) -> datetime | None:
    """The UTC instant for a naive UK wall-clock time.

    Returns ``None`` for a time that does not exist (the spring-forward hour).
    In the repeated autumn hour, ``fold=0`` is the first (BST) occurrence and
    ``fold=1`` the second (GMT) — the same convention as :pep:`495`.
    """
    candidates = []
    for offset in (_BST, _GMT):
        utc = (local - offset).replace(tzinfo=UTC)
        if utc_offset(utc) == offset:
            candidates.append(utc)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return candidates[1] if fold else candidates[0]


def local_midnight_utc(day: date) -> datetime:
    """UTC instant of local midnight starting ``day``.

    Local midnight is never inside a clock change (changes happen at 01:00 UTC),
    so it always exists and is unique.
    """
    utc = local_to_utc(datetime.combine(day, datetime.min.time()))
    if utc is None:  # pragma: no cover — impossible under the current rule
        raise ValueError(f"local midnight of {day} does not exist")
    return utc


def periods_in_day(day: date) -> int:
    """Half-hour settlement periods in the UK local day: 46, 48 or 50."""
    span = local_midnight_utc(day + timedelta(days=1)) - local_midnight_utc(day)
    return int(span / _HALF_HOUR)


__all__ = [
    "bst_bounds",
    "local_midnight_utc",
    "local_to_utc",
    "periods_in_day",
    "to_local",
    "utc_offset",
]
