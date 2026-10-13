"""Supplier half-hourly CSV import: layout, clock days, flags, and what is NOT a reading."""

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain.hh_import import parse_hh_csv

_HEAD48 = ",".join(f"HH{i:02d}" for i in range(1, 49))
_HEAD50 = ",".join(f"HH{i:02d}" for i in range(1, 51))


def _wide_row(mpan: str, day: str, values: list[str]) -> str:
    return f"{mpan},{day}," + ",".join(values)


@pytest.mark.unit
def test_wide_ordinary_day():
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("1200000000001", "15/01/2026", ["1.5"] * 48)
    out = parse_hh_csv(text)
    assert out.layout == "wide"
    assert out.meters == ("1200000000001",)
    assert len(out.intervals) == 48
    assert out.intervals[0].start_utc == datetime(2026, 1, 15, tzinfo=UTC)
    assert out.intervals[-1].start_utc == datetime(2026, 1, 15, 23, 30, tzinfo=UTC)
    assert all(iv.kwh == 1.5 for iv in out.intervals)


@pytest.mark.unit
def test_wide_summer_day_starts_at_2300_utc():
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "01/07/2026", ["1"] * 48)
    out = parse_hh_csv(text)
    assert out.intervals[0].start_utc == datetime(2026, 6, 30, 23, tzinfo=UTC)


@pytest.mark.unit
def test_blank_cell_is_missing_not_zero():
    values = ["1"] * 48
    values[10] = ""
    values[11] = "n/a"
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "15/01/2026", values)
    out = parse_hh_csv(text)
    assert len(out.intervals) == 46
    assert all(iv.kwh == 1.0 for iv in out.intervals)
    assert out.counts["blank_or_non_numeric"] == 2


@pytest.mark.unit
def test_short_day_with_48_columns_and_blank_tail_is_fine():
    values = ["1"] * 46 + ["", ""]
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "29/03/2026", values)
    out = parse_hh_csv(text)
    assert len(out.intervals) == 46
    assert out.counts["rows_rejected"] == 0


@pytest.mark.unit
def test_short_day_with_values_beyond_46_is_rejected():
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "29/03/2026", ["1"] * 48)
    out = parse_hh_csv(text)
    assert out.intervals == ()
    assert out.counts["rows_rejected"] == 1
    assert any("46" in w for w in out.warnings)


@pytest.mark.unit
def test_long_day_in_48_column_file_leaves_last_two_periods_missing():
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "25/10/2026", ["1"] * 48)
    out = parse_hh_csv(text)
    assert len(out.intervals) == 48
    assert out.counts["missing_long_day_periods"] == 2


@pytest.mark.unit
def test_long_day_in_50_column_file():
    text = f"MPAN,Date,{_HEAD50}\n" + _wide_row("M1", "25/10/2026", ["1"] * 50)
    out = parse_hh_csv(text)
    starts = [iv.start_utc for iv in out.intervals]
    assert len(starts) == 50
    assert starts[-1] - starts[0] == timedelta(hours=24, minutes=30)


@pytest.mark.unit
def test_us_date_is_rejected_not_reinterpreted():
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "01/13/2026", ["1"] * 48)
    out = parse_hh_csv(text)
    assert out.intervals == ()
    assert out.counts["rows_rejected"] == 1


@pytest.mark.unit
@pytest.mark.parametrize("day", ["2026-01-15", "15-01-2026", "15/01/26", "15-Jan-2026"])
def test_accepted_date_formats(day):
    text = f"Date,{_HEAD48}\n{day}," + ",".join(["1"] * 48)
    out = parse_hh_csv(text)
    assert out.intervals[0].start_utc == datetime(2026, 1, 15, tzinfo=UTC)
    assert out.meters == ("(unnamed)",)


@pytest.mark.unit
def test_no_flag_column_means_unknown_not_actual():
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "15/01/2026", ["1"] * 48)
    out = parse_hh_csv(text)
    assert all(iv.estimated is None for iv in out.intervals)


@pytest.mark.unit
def test_row_read_type_flags():
    head = f"MPAN,Date,Read Type,{_HEAD48}"
    rows = [
        "M1,15/01/2026,A," + ",".join(["1"] * 48),
        "M1,16/01/2026,E," + ",".join(["1"] * 48),
        "M1,17/01/2026,Z," + ",".join(["1"] * 48),
    ]
    out = parse_hh_csv("\n".join([head, *rows]))
    by_day = {}
    for iv in out.intervals:
        by_day.setdefault(iv.start_utc.day, set()).add(iv.estimated)
    assert by_day == {15: {False}, 16: {True}, 17: {True}}
    assert any("Z" in w for w in out.warnings)


@pytest.mark.unit
def test_per_period_flag_columns():
    cols = []
    vals = []
    for i in range(1, 49):
        cols += [f"HH{i:02d}", f"HH{i:02d} Flag"]
        vals += ["2", "E" if i == 3 else "A"]
    text = "Date," + ",".join(cols) + "\n15/01/2026," + ",".join(vals)
    out = parse_hh_csv(text)
    assert len(out.intervals) == 48
    assert [iv.estimated for iv in out.intervals].count(True) == 1
    assert out.intervals[2].estimated is True


@pytest.mark.unit
def test_negative_is_rejected_with_warning():
    values = ["1"] * 48
    values[0] = "-0.5"
    text = f"MPAN,Date,{_HEAD48}\n" + _wide_row("M1", "15/01/2026", values)
    out = parse_hh_csv(text)
    assert len(out.intervals) == 47
    assert out.counts["negative_rejected"] == 1


@pytest.mark.unit
def test_duplicates_keep_first_and_count_conflicts():
    head = f"MPAN,Date,{_HEAD48}\n"
    text = (
        head
        + _wide_row("M1", "15/01/2026", ["1"] * 48)
        + "\n"
        + _wide_row("M1", "15/01/2026", ["2"] * 48)
    )
    out = parse_hh_csv(text)
    assert len(out.intervals) == 48
    assert all(iv.kwh == 1.0 for iv in out.intervals)
    assert out.counts["duplicate_conflicting"] == 48


@pytest.mark.unit
def test_wide_unit_assumed_kwh_and_said_so():
    text = f"Date,{_HEAD48}\n15/01/2026," + ",".join(["1"] * 48)
    out = parse_hh_csv(text)
    assert any("kWh" in a for a in out.assumptions)


@pytest.mark.unit
def test_long_layout_naive_local_start():
    text = "Timestamp,Consumption (kWh),Flag\n01/07/2026 00:00,1.2,A\n01/07/2026 00:30,1.4,E\n"
    out = parse_hh_csv(text)
    assert out.layout == "long"
    assert out.intervals[0].start_utc == datetime(2026, 6, 30, 23, tzinfo=UTC)
    assert out.intervals[1].estimated is True


@pytest.mark.unit
def test_long_layout_end_convention_shifts_back():
    text = "Timestamp,kWh\n15/01/2026 00:30,1\n"
    out = parse_hh_csv(text, timestamp_marks="end")
    assert out.intervals[0].start_utc == datetime(2026, 1, 15, tzinfo=UTC)


@pytest.mark.unit
def test_long_layout_kw_converted_to_kwh():
    text = "Timestamp,Demand (kW)\n2026-01-15T00:00:00Z,10\n"
    out = parse_hh_csv(text)
    assert out.intervals[0].kwh == 5.0


@pytest.mark.unit
def test_long_layout_wh():
    text = "Timestamp,Energy Wh\n2026-01-15 00:00,1500\n"
    assert parse_hh_csv(text).intervals[0].kwh == 1.5


@pytest.mark.unit
def test_long_layout_separate_date_and_time():
    text = "Date,Time,kWh\n15/01/2026,00:00,1\n15/01/2026,00:30,2\n"
    out = parse_hh_csv(text)
    assert [iv.kwh for iv in out.intervals] == [1.0, 2.0]


@pytest.mark.unit
def test_long_layout_repeated_autumn_hour_uses_second_occurrence():
    rows = ["25/10/2026 01:00,1", "25/10/2026 01:30,1", "25/10/2026 01:00,2", "25/10/2026 01:30,2"]
    out = parse_hh_csv("Timestamp,kWh\n" + "\n".join(rows))
    assert len(out.intervals) == 4
    assert out.counts["duplicate_conflicting"] == 0


@pytest.mark.unit
def test_long_layout_spring_gap_rejected():
    out = parse_hh_csv("Timestamp,kWh\n29/03/2026 01:30,1\n")
    assert out.intervals == ()
    assert out.counts["rows_rejected"] == 1


@pytest.mark.unit
def test_long_layout_off_grid_timestamp_rejected():
    out = parse_hh_csv("Timestamp,kWh\n15/01/2026 00:10,1\n")
    assert out.intervals == ()


@pytest.mark.unit
def test_unrecognised_layout_raises():
    with pytest.raises(ValueError, match="layout"):
        parse_hh_csv("foo,bar\n1,2\n")


@pytest.mark.unit
def test_empty_raises():
    with pytest.raises(ValueError):
        parse_hh_csv("")


@pytest.mark.unit
def test_size_cap():
    with pytest.raises(ValueError, match="too large"):
        parse_hh_csv("x" * (60 * 1024 * 1024))


@pytest.mark.unit
def test_bad_option_values():
    text = "Timestamp,kWh\n15/01/2026 00:00,1\n"
    with pytest.raises(ValueError):
        parse_hh_csv(text, unit="mwh")
    with pytest.raises(ValueError):
        parse_hh_csv(text, timestamp_marks="middle")


@pytest.mark.unit
def test_intervals_sorted_and_frozen():
    text = "Timestamp,kWh\n15/01/2026 01:00,1\n15/01/2026 00:00,1\n"
    out = parse_hh_csv(text)
    assert out.intervals[0].start_utc < out.intervals[1].start_utc
    with pytest.raises(AttributeError):
        out.intervals[0].kwh = 3  # type: ignore[misc]
