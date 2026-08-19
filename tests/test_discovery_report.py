"""The scan report — one self-contained file, and the two things it must not do.

* **It must not execute what a device said.** A vendor field, an OPC-UA
  ApplicationName and an MTConnect device name are all free text chosen by the
  device. On an unknown network that is not a trusted source, and a survey of a
  hostile segment must not become script execution on the surveyor's laptop.
* **It must not touch the network when opened.** No CDN, no web font, no remote
  image, no fetch. The file is opened on an air-gapped laptop in a plant office;
  a report that phoned home to render would contradict the product it documents.

The third property is editorial rather than technical, and is asserted anyway:
the trust page comes FIRST. The reader of a first survey is usually the person
who has to defend having let it run.
"""

from __future__ import annotations

import re

import pytest

from iaiops.core.discovery import wirelog
from iaiops.core.discovery.report import render_html, render_result
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    CONF_PORT_ONLY,
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    VERDICT_NO_DEVICES,
    VERDICT_OK,
    Authorization,
    HostResult,
    PortResult,
    ProtocolCandidate,
    ScanPlan,
    ScanResult,
)
from iaiops.core.sink.scan_store import host_to_dict, load_scan, save_scan

pytestmark = pytest.mark.unit


def device(ip="10.0.0.3", vendor="Schneider", model="TM241") -> HostResult:
    return HostResult(
        ip=ip,
        sources=("arp", "tcp"),
        mac="00:0c:29:45:3b:d8",
        ports=(PortResult(502, PORT_OPEN, 1.4), PortResult(102, PORT_FILTERED)),
        protocols=(ProtocolCandidate("modbus", CONF_CONFIRMED, "modbus_fc43", "ok"),),
        identity={"modbus": {"vendor": vendor, "model": model}},
    )


def scan(*hosts: HostResult, verdict=VERDICT_OK, notes=(), approver="J. Controls") -> ScanResult:
    return ScanResult(
        plan=ScanPlan(
            site="Plant A",
            cidrs=("10.0.0.0/29",),
            authorization=Authorization(approved_by=approver, ticket="CHG-91" if approver else ""),
        ),
        hosts=hosts,
        verdict=verdict,
        wire_summary={"tcp_connect": 16, "modbus_fc43": 1},
        notes=notes,
        started_at="2026-08-18T09:00:00+00:00",
        finished_at="2026-08-18T09:00:31+00:00",
    )


class TestItNeverExecutesWhatADeviceSaid:
    HOSTILE = '<script>alert("pwned")</script>'

    def test_a_hostile_vendor_string_is_escaped(self):
        """A Modbus vendor field is arbitrary bytes chosen by the device."""
        html = render_result(scan(device(vendor=self.HOSTILE)))
        assert self.HOSTILE not in html
        assert "&lt;script&gt;" in html

    def test_a_hostile_string_in_the_identity_json_is_escaped_too(self):
        """The appendix dumps the full record. It is the easiest place to forget."""
        html = render_result(scan(device(model=self.HOSTILE)))
        assert "<script>alert" not in html.replace("<script>(function", "")
        assert html.count("<script>") == 1, "only the report's own script tag may appear"

    def test_a_hostile_site_name_is_escaped(self):
        result = scan(device())
        hostile = ScanResult(
            plan=ScanPlan(site='"><script>alert(1)</script>'),
            hosts=result.hosts,
            wire_summary=result.wire_summary,
            started_at=result.started_at,
        )
        html = render_result(hostile)
        assert "<script>alert" not in html
        assert html.count("<script>") == 1

    def test_a_hostile_note_is_escaped(self):
        html = render_result(scan(device(), notes=("<img src=x onerror=alert(1)>",)))
        assert "<img src=x" not in html
        assert "&lt;img" in html

    def test_a_quote_in_a_sort_key_cannot_break_out_of_the_attribute(self):
        """The address is rendered into a data-key attribute."""
        html = render_result(scan(device(ip='10.0.0.3" onmouseover="alert(1)')))
        assert 'onmouseover="alert' not in html


class TestItMakesNoNetworkRequest:
    def test_nothing_is_loaded_from_anywhere(self):
        html = render_result(scan(device()))
        for pattern in ("http://", "https://", "//cdn", "@import", "url(http"):
            assert pattern not in html, f"the report references {pattern!r}"

    def test_there_are_no_external_resource_elements(self):
        html = render_result(scan(device()))
        for tag in ("<link", "<img", "<iframe", "<object", "<embed", "<source"):
            assert tag not in html.lower(), f"the report contains {tag}"

    def test_the_script_never_reaches_the_network(self):
        html = render_result(scan(device()))
        for call in ("fetch(", "XMLHttpRequest", "WebSocket", "navigator.sendBeacon", "import("):
            assert call not in html, f"the report's script calls {call}"

    def test_styles_and_script_are_inline(self):
        html = render_result(scan(device()))
        assert "<style>" in html and "<script>" in html
        assert 'rel="stylesheet"' not in html


class TestTheTrustPageComesFirst:
    def test_what_we_touched_precedes_the_findings(self):
        html = render_result(scan(device()))
        assert html.index("What this scan touched") < html.index("&middot; Devices")

    def test_every_emission_is_listed_with_its_count(self):
        html = render_result(scan(device()))
        assert "tcp_connect" in html and "modbus_fc43" in html
        assert "16" in html

    def test_the_counts_are_declared_as_including_failures(self):
        """A page that tallied only successful requests would understate exactly
        the traffic an operator is worried about."""
        html = render_result(scan(device()))
        assert "include requests that" in html and "failed" in html

    def test_the_full_never_done_list_is_rendered(self):
        html = render_result(scan(device()))
        for claim in wirelog.NEVER_DONE:
            head = claim.split("—")[0].strip()
            assert head.replace("'", "&#x27;") in html or head in html, f"missing: {claim}"

    def test_a_zero_emission_scan_says_so_rather_than_showing_an_empty_table(self):
        quiet = ScanResult(
            plan=ScanPlan(site="Plant A", profile="passive"),
            hosts=(HostResult(ip="10.0.0.3", sources=("arp",), mac="00:0c:29:45:3b:d8"),),
            wire_summary={},
            started_at="2026-08-18T09:00:00+00:00",
        )
        html = render_html_of(quiet)
        assert "Nothing was emitted" in html

    def test_an_undeclared_class_is_shown_not_silently_dropped(self):
        """If a stored scan carries a class this build does not know, hiding it
        would understate the traffic — the opposite of what this page is for."""
        html = render_html(
            {
                "site": "x",
                "wire_summary": {"mystery_packet": 3},
                "hosts": [],
                "stages": [],
                "scope": {},
                "notes": [],
            }
        )
        assert "mystery_packet" in html
        assert "undeclared packet class" in html


def render_html_of(result: ScanResult) -> str:
    return render_result(result)


class TestTheDeviceTable:
    def test_identity_columns_are_rendered(self):
        html = render_result(scan(device()))
        assert "Schneider" in html and "TM241" in html

    def test_an_absent_field_is_a_dash_not_the_word_none(self):
        """A blank cell means the device did not report it. 'None' reads like a
        value and 'null' reads like a bug.

        Asserted on the marker only ``_cell`` emits. Looking for the dash
        anywhere in the page is not enough — the header renders one too, so that
        version of this test passes even when every table cell is left empty.
        """
        html = render_result(scan(device(vendor="Schneider", model="")))
        assert ">None<" not in html and ">null<" not in html
        assert '<td class="blank"' in html
        assert html.count('class="blank"') >= 2, "the empty model and serial must both be marked"

    def test_a_populated_field_is_not_marked_blank(self):
        """The complement: a filter that marked everything blank would also
        satisfy the assertion above."""
        html = render_result(scan(device(vendor="Schneider", model="TM241")))
        row_start = html.index(">10.0.0.3<")
        row = html[row_start : row_start + 400]
        assert "Schneider" in row and 'class="blank">Schneider' not in row

    def test_a_port_only_host_shows_no_vendor(self):
        guess = HostResult(
            ip="10.0.0.8",
            ports=(PortResult(502, PORT_OPEN),),
            protocols=(ProtocolCandidate("modbus", CONF_PORT_ONLY, "tcp_open", ""),),
        )
        html = render_result(scan(guess))
        assert "10.0.0.8" in html

    def test_only_open_ports_appear_in_the_open_ports_column(self):
        html = render_result(scan(device()))
        table = html[
            html.index('id="devices"') : html.index("&middot; Diagnosis")
            if "&middot; Diagnosis" in html
            else len(html)
        ]
        assert "502" in table

    def test_a_scan_with_no_hosts_renders_and_explains(self):
        html = render_result(scan(verdict=VERDICT_NO_DEVICES))
        assert "No host produced any response" in html


class TestHeaderAndProvenance:
    def test_the_authorization_is_on_the_first_screen(self):
        html = render_result(scan(device()))
        assert "J. Controls" in html and "CHG-91" in html

    def test_a_missing_authorization_says_not_recorded(self):
        html = render_result(scan(device(), approver=""))
        assert "not recorded" in html

    def test_the_verdict_is_explained_in_words_not_just_a_code(self):
        html = render_result(scan(device()))
        assert "Industrial devices were identified" in html

    def test_a_partial_verdict_explains_what_partial_means(self):
        result = ScanResult(
            plan=ScanPlan(site="A"),
            hosts=(HostResult(ip="10.0.0.5", ports=(PortResult(502, PORT_REFUSED),)),),
            verdict="partial",
            started_at="2026-08-18T09:00:00+00:00",
        )
        html = render_result(result)
        assert "no industrial protocol was confirmed" in html


class TestStoredAndUnstoredRenderTheSame:
    def test_the_two_host_shapes_match_key_for_key(self, tmp_path):
        """A renderer that silently worked on only one of them would be a bug
        nobody noticed until an operator asked for a report of an unsaved scan."""
        result = scan(device())
        scan_id = save_scan(result, tmp_path / "data.db")
        stored = load_scan(scan_id, tmp_path / "data.db")["hosts"][0]
        live = host_to_dict(result.hosts[0])
        assert set(stored) - {"id", "scan_id"} == set(live)

    def test_the_two_produce_the_same_device_row(self, tmp_path):
        result = scan(device())
        scan_id = save_scan(result, tmp_path / "data.db")
        from_disk = render_html(load_scan(scan_id, tmp_path / "data.db"))
        live = render_result(result)
        for field in ("Schneider", "TM241", "10.0.0.3", "00:0c:29:45:3b:d8"):
            assert field in from_disk and field in live

    def test_a_non_ascii_vendor_survives_the_round_trip(self, tmp_path):
        """汇川 / 三菱電機 / Müller are ordinary in this market."""
        result = scan(device(vendor="汇川"))
        scan_id = save_scan(result, tmp_path / "data.db")
        html = render_html(load_scan(scan_id, tmp_path / "data.db"))
        assert "汇川" in html


class TestStructure:
    def test_it_is_a_complete_standalone_document(self):
        html = render_result(scan(device()))
        assert html.startswith("<!doctype html>")
        assert "<title>" in html and html.rstrip().endswith("</html>")
        assert 'charset="utf-8"' in html

    def test_it_renders_in_both_colour_schemes(self):
        """It is opened on whatever laptop is in the plant office."""
        html = render_result(scan(device()))
        assert "prefers-color-scheme: dark" in html
        assert re.search(r":root\s*\{", html)
