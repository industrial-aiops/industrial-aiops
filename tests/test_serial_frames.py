"""E4 (HLD §17.4, D53–D58): serial ASCII instruments — the pure part.

A line such as ``ST,GS,+0012.34kg`` is decoded by an ``ascii`` layout: a regex
that must match the WHOLE line, a ``value`` group, an optional status group
whose codes are ``ok`` or named invalid (unstable / overload → gaps), and the
unit fixed or taken from a group (both → must agree). Rule 5: a line that does
not match is refused, never "parsed as best we can".
"""

from __future__ import annotations

import pytest

from iaiops.connectors.serial.frames import LineFramer, decode_line
from iaiops.core.runtime.sensor import InvalidReadingError, parse_profile

pytestmark = pytest.mark.unit

SCALE = {
    "id": "scale",
    "protocol": "serial",
    "source": "manual",
    "verified": "待核实",
    "framing": {"terminator": "\r\n", "encoding": "ascii", "max_line": 64},
    "mode": "listen",
    "channels": [
        {
            "name": "weight",
            "layout": {
                "pattern": (
                    r"(?P<status>ST|US|OL),(?P<kind>GS|NT),"
                    r"(?P<value>[+-]?\d+\.\d+)(?P<unit>kg|g)"
                )
            },
            "unit": "kg",
            "unit_from": "unit",
            "status": {
                "field": "status",
                "ok": ["ST"],
                "invalid": {"US": "unstable", "OL": "overload"},
            },
            "signal": "level",
        }
    ],
}


def _profile(**over):
    raw = {**SCALE, **over}
    return parse_profile(raw)


def _weight(**over):
    return _profile(**over).channel("weight")


# ── decoding ────────────────────────────────────────────────────────────────


def test_a_stable_line_decodes():
    reading = decode_line(_weight(), "ST,GS,+0012.34kg")
    assert reading.value == pytest.approx(12.34) and reading.unit == "kg"


@pytest.mark.parametrize(
    ("line", "why"), [("US,GS,+0012.34kg", "unstable"), ("OL,GS,+9999.99kg", "overload")]
)
def test_invalid_status_codes_are_gaps(line, why):
    with pytest.raises(InvalidReadingError, match=why):
        decode_line(_weight(), line)


def test_an_unknown_status_code_is_a_gap():
    profile = dict(SCALE)
    profile["channels"] = [
        {
            **SCALE["channels"][0],
            "layout": {
                "pattern": (
                    r"(?P<status>\w\w),(?P<kind>GS|NT),"
                    r"(?P<value>[+-]?\d+\.\d+)(?P<unit>kg|g)"
                )
            },
        }
    ]
    with pytest.raises(InvalidReadingError, match="status"):
        decode_line(parse_profile(profile).channel("weight"), "ZZ,GS,+0012.34kg")


@pytest.mark.parametrize("line", ["ST,GS,+0012.3", "xST,GS,+0012.34kg", "ST,GS,+0012.34kgx", ""])
def test_a_line_that_does_not_fully_match_is_refused(line):
    with pytest.raises(InvalidReadingError, match="match"):
        decode_line(_weight(), line)


def test_a_unit_that_disagrees_with_the_declared_one_is_refused():
    with pytest.raises(InvalidReadingError, match="unit"):
        decode_line(_weight(), "ST,GS,+0012.34g")


def test_unit_only_from_the_line_is_refused_at_load():
    """A unit taken only from each line is not one series' unit (review of E4)."""
    channel = {**SCALE["channels"][0]}
    channel.pop("unit")
    with pytest.raises(ValueError, match="fixed unit"):
        _profile(channels=[channel])


def test_scale_and_range_apply():
    channel = {
        **SCALE["channels"][0],
        "scale": 1000,
        "unit": "g",
        "unit_from": None,
        "range": [0, 50000],
    }
    channel.pop("unit_from")
    reading = decode_line(_profile(channels=[channel]).channel("weight"), "ST,GS,+0012.34kg")
    assert reading.value == pytest.approx(12340)
    with pytest.raises(InvalidReadingError, match="range"):
        decode_line(_profile(channels=[channel]).channel("weight"), "ST,GS,+0099.00kg")


# ── profile validation ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"mode": None}, "mode"),
        ({"mode": "stream"}, "mode"),
        ({"mode": "poll"}, "query"),  # poll needs its query
        ({"query": "P\r\n"}, "query"),  # listen takes none
        ({"framing": {"terminator": "", "encoding": "ascii"}}, "terminator"),
        ({"framing": {"terminator": "\r\n", "encoding": "ebcdic"}}, "encoding"),
    ],
)
def test_serial_profile_rules(over, message):
    raw = {**SCALE, **over}
    raw = {k: v for k, v in raw.items() if v is not None}
    with pytest.raises(ValueError, match=message):
        parse_profile(raw)


@pytest.mark.parametrize(
    ("layout", "extra", "message"),
    [
        ({"pattern": r"(?P<value>\d+"}, {}, "pattern"),  # does not compile
        ({"pattern": r"(?P<v>\d+)"}, {}, "value"),  # no value group
        ({"pattern": r"(?P<value>\d+)"}, {"unit_from": "unit"}, "unit_from"),  # group missing
        ({"pattern": r"(?P<value>\d+)", "extra": 1}, {}, "unknown"),
    ],
)
def test_ascii_layout_rules(layout, extra, message):
    channel = {"name": "weight", "layout": layout, "unit": "kg", "signal": "level", **extra}
    with pytest.raises(ValueError, match=message):
        _profile(channels=[channel])


def test_a_poll_query_is_short_printable_and_from_the_profile_only():
    with pytest.raises(ValueError, match="query"):
        _profile(mode="poll", query="P" * 80)
    with pytest.raises(ValueError, match="query"):
        _profile(mode="poll", query="P\x00")
    assert _profile(mode="poll", query="P\r\n").query == "P\r\n"


def test_framing_and_mode_are_serial_only():
    from iaiops.core.runtime.sensor import parse_profile as parse

    with pytest.raises(ValueError, match="serial"):
        parse(
            {
                "id": "m",
                "protocol": "modbus",
                "source": "manual",
                "verified": "待核实",
                "mode": "listen",
                "channels": [
                    {
                        "name": "c",
                        "layout": {"table": "input", "address": 0, "type": "uint16"},
                        "unit": "u",
                        "signal": "level",
                    }
                ],
            }
        )


# ── framing ─────────────────────────────────────────────────────────────────


def test_framer_splits_lines_across_chunks():
    framer = LineFramer(terminator="\r\n", encoding="ascii", max_line=64)
    assert framer.feed(b"ST,GS,+0001.00kg\r\nST,GS,+00") == [("ST,GS,+0001.00kg", "")]
    assert framer.feed(b"02.00kg\r\n") == [("ST,GS,+0002.00kg", "")]


def test_framer_marks_an_overlong_line_instead_of_merging_it():
    framer = LineFramer(terminator="\r\n", encoding="ascii", max_line=8)
    out = framer.feed(b"0123456789ABCDEF\r\nOK\r\n")
    assert out[0][0] is None and "longer" in out[0][1]
    assert out[1] == ("OK", "")


def test_framer_marks_undecodable_bytes():
    framer = LineFramer(terminator="\n", encoding="ascii", max_line=64)
    out = framer.feed(b"ST,\xff\xfe\n")
    assert out[0][0] is None and "ascii" in out[0][1]
