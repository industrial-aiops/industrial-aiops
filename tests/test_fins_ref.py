"""Parsing an Omron FINS point reference, so FINS lines can be sampled.

`readiness` reports which endpoints can be collected from, and FINS was absent
from that list purely because nothing mapped a single point reference onto the
connector's existing `fins_read_words` / `fins_read_bits`. Omron is not a corner
case in Asian plants, and the point of the capability registry is that adding
one is a registration rather than a build.

The parser refuses rather than guesses, because a FINS reference is
area-qualified and the areas mean different memory: `DM100` and `CIO100` are
different values in different places, and an unqualified `100` cannot be
resolved into either without inventing an answer. Guessing "probably DM" would
produce readings from the wrong memory that look entirely plausible.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.fins.ops import parse_fins_ref

pytestmark = pytest.mark.unit


class TestWordReferences:
    @pytest.mark.parametrize(
        ("ref", "area", "address"),
        [
            ("DM100", "DM", 100),
            ("dm100", "DM", 100),
            ("CIO0", "CIO", 0),
            ("W32", "W", 32),
            ("H5", "H", 5),
            ("A501", "A", 501),
            ("EM1000", "EM", 1000),
            ("  DM 100  ", "DM", 100),
        ],
    )
    def test_area_and_address_are_read_off(self, ref, area, address):
        parsed = parse_fins_ref(ref)
        assert (parsed.area, parsed.address, parsed.bit) == (area, address, None)


class TestBitReferences:
    def test_a_dotted_suffix_selects_a_bit(self):
        parsed = parse_fins_ref("CIO0.05")
        assert (parsed.area, parsed.address, parsed.bit) == ("CIO", 0, 5)

    def test_a_bit_without_a_leading_zero_works(self):
        assert parse_fins_ref("W10.3").bit == 3

    def test_bit_15_is_the_top_of_a_word(self):
        assert parse_fins_ref("DM7.15").bit == 15

    def test_a_bit_above_15_is_refused(self):
        """Sixteen bits to a word — 16 is a typo, not an address."""
        with pytest.raises(ValueError, match="(?i)bit"):
            parse_fins_ref("DM7.16")

    def test_an_area_without_bit_access_is_refused_for_bits(self):
        """EM has no bit code; silently reading the whole word instead would
        return a number where a boolean was asked for."""
        with pytest.raises(ValueError, match="(?i)bit"):
            parse_fins_ref("EM100.2")


class TestItRefusesRatherThanGuesses:
    def test_a_bare_number_is_refused(self):
        """`DM100` and `CIO100` are different memory. Assuming one would return
        a plausible reading from the wrong place."""
        with pytest.raises(ValueError, match="(?i)area"):
            parse_fins_ref("100")

    def test_the_refusal_lists_every_area(self):
        """Checks ALL of them, not just the two that appear in the example.

        The first version asserted "DM" and "CIO" were present — and they are,
        inside the worked example `e.g. 'DM100' or 'CIO0.05'`. Removing the area
        list entirely left that test green, which is the wrong reason to pass.
        """
        from iaiops.connectors.fins.client import MEMORY_AREAS

        with pytest.raises(ValueError) as excinfo:
            parse_fins_ref("100")
        message = str(excinfo.value)
        missing = [a for a in MEMORY_AREAS if a not in message]
        assert not missing, f"the refusal does not name {missing}"

    def test_an_unknown_area_is_refused(self):
        with pytest.raises(ValueError, match="(?i)area"):
            parse_fins_ref("ZZ100")

    def test_an_area_without_an_address_is_refused(self):
        with pytest.raises(ValueError):
            parse_fins_ref("DM")

    def test_an_empty_reference_is_refused(self):
        with pytest.raises(ValueError):
            parse_fins_ref("")

    def test_a_negative_address_is_refused(self):
        with pytest.raises(ValueError):
            parse_fins_ref("DM-5")


class TestItIsRegisteredForCollection:
    def test_fins_can_now_be_collected_from(self):
        from iaiops.core.collect.reader import can_collect

        assert can_collect("fins") is True

    def test_it_appears_in_the_collectable_list(self):
        from iaiops.core.collect.reader import collectable_protocols

        assert "fins" in collectable_protocols()

    def test_the_capability_reads_a_word_through_the_connector(self, monkeypatch):
        """The registration is wired to the real read path, not a stub."""
        seen = {}

        def fake_read(target, area="DM", address=0, count=1):
            seen.update(area=area, address=address, count=count)
            return {"words": [4242]}

        monkeypatch.setattr("iaiops.connectors.fins.ops.fins_read_words", fake_read)
        from iaiops.core.collect.reader import read_point

        class T:
            protocol = "fins"

        value, _ = read_point(T(), "DM100")
        assert value == 4242
        assert seen == {"area": "DM", "address": 100, "count": 1}

    def test_a_bit_reference_goes_through_the_bit_path(self, monkeypatch):
        seen = {}

        def fake_bits(target, area="CIO", address=0, bit=0, count=1):
            seen.update(area=area, address=address, bit=bit)
            return {"bits": [True]}

        monkeypatch.setattr("iaiops.connectors.fins.ops.fins_read_bits", fake_bits)
        from iaiops.core.collect.reader import read_point

        class T:
            protocol = "fins"

        value, _ = read_point(T(), "CIO0.05")
        assert value is True
        assert seen == {"area": "CIO", "address": 0, "bit": 5}
