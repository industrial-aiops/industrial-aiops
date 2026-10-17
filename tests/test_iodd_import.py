"""IODD import → a DRAFT profile (HLD §16.3 rule 2).

Parsing an IODD is deterministic, but its result is still not a fact: the draft
says `source: iodd, verified: 待核实`, keeps IODD unit codes unmapped, and says
which fields were assumed. Anything the importer cannot represent is listed, not
dropped in silence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from iaiops.core.runtime.sensor import parse_profile
from iaiops.core.runtime.sensor.iodd import import_iodd, render_draft

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "iodd" / "distance_sensor.xml"


@pytest.fixture
def draft():
    return import_iodd(FIXTURE.read_text("utf-8"))


def test_draft_is_marked_unverified_and_carries_the_identity(draft):
    profile = draft.profile
    assert profile["source"] == "iodd" and profile["verified"] == "待核实"
    assert profile["protocol"] == "iolink"
    assert profile["match"] == {"vendor_id": 888, "device_id": 4660}


def test_record_items_become_channels_with_iodd_bit_offsets(draft):
    channels = {c["name"]: c for c in draft.profile["channels"]}
    assert set(channels) == {"distance", "device_temperature", "switching_signal_1"}
    assert channels["distance"]["layout"] == {"bit_offset": 16, "bit_length": 16, "type": "uint"}
    assert channels["device_temperature"]["layout"]["type"] == "int"
    assert channels["switching_signal_1"]["layout"] == {
        "bit_offset": 0,
        "bit_length": 1,
        "type": "uint",
    }


def test_gradient_and_value_range_become_scale_and_engineering_range(draft):
    distance = {c["name"]: c for c in draft.profile["channels"]}["distance"]
    assert distance["scale"] == pytest.approx(0.1)
    assert distance["range"] == [pytest.approx(50.0), pytest.approx(6000.0)]


def test_named_values_outside_the_range_become_sentinels_inside_do_not(draft):
    channels = {c["name"]: c for c in draft.profile["channels"]}
    assert channels["distance"]["invalid"] == [{"raw": 65535, "meaning": "No target"}]
    # -128 in an 8-bit signed field is the raw octet 0x80.
    assert channels["device_temperature"]["invalid"] == [
        {"raw": 0x80, "meaning": "Temperature sensor fault"}
    ]


def test_units_are_not_guessed(draft):
    channels = {c["name"]: c for c in draft.profile["channels"]}
    assert "1013" in channels["distance"]["unit"] and "待核实" in channels["distance"]["unit"]
    assert "待核实" in channels["device_temperature"]["unit"]


def test_unrepresentable_items_are_listed_not_dropped(draft):
    assert any("Label" in note and "StringT" in note for note in draft.notes)


def test_the_rendered_draft_is_a_valid_profile(draft):
    text = render_draft(draft, source_name="distance_sensor.xml")
    assert "待核实" in text and "assumed" in text
    profile = parse_profile(yaml.safe_load(text))
    assert profile.vendor_id == 888 and profile.verified == "待核实"


def test_doctype_is_refused():
    text = FIXTURE.read_text("utf-8").replace(
        "<IODevice", '<!DOCTYPE x [<!ENTITY e "boom">]>\n<IODevice', 1
    )
    with pytest.raises(ValueError, match="DOCTYPE|ENTITY"):
        import_iodd(text)


def test_several_process_data_variants_need_a_choice():
    text = FIXTURE.read_text("utf-8")
    second = text[
        text.index("<ProcessData id=") : text.index("</ProcessData>") + len("</ProcessData>")
    ]
    doubled = text.replace(second, second + second.replace('id="PD"', 'id="PD2"'), 1)
    with pytest.raises(ValueError, match="PD, PD2"):
        import_iodd(doubled)
    assert import_iodd(doubled, process_data="PD2").profile["channels"]


def test_not_an_iodd_is_refused():
    with pytest.raises(ValueError, match="IODevice"):
        import_iodd("<root/>")


def test_malformed_xml_is_refused():
    with pytest.raises(ValueError, match="XML"):
        import_iodd("<IODevice")
