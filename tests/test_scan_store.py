"""The on-box scan store — where a survey stops being in memory.

Two properties carry most of the weight:

* **Storing is idempotent.** A scan saved twice is one survey. A store that
  appended instead would make the next comparison report change that never
  happened, which is the single most damaging thing a change-detection product
  can do.
* **The flat columns come from ONE protocol and say which.** A row that merged a
  Modbus vendor with an OPC-UA model would describe a device that does not
  exist. Both identities survive in JSON regardless.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    CONF_PORT_ONLY,
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    VERDICT_OK,
    Authorization,
    HostResult,
    PortResult,
    ProtocolCandidate,
    ScanPlan,
    ScanResult,
)
from iaiops.core.sink.scan_store import (
    IDENTITY_COLUMNS,
    ScanNotFound,
    list_scans,
    load_scan,
    prune_scans,
    save_scan,
    scan_id_for,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


def plc(ip="10.0.0.3") -> HostResult:
    return HostResult(
        ip=ip,
        sources=("arp", "tcp"),
        mac="00:0c:29:45:3b:d8",
        ports=(
            PortResult(102, PORT_FILTERED),
            PortResult(502, PORT_OPEN, rtt_ms=1.4),
        ),
        protocols=(ProtocolCandidate("modbus", CONF_CONFIRMED, "modbus_fc43", "vendor=Schneider"),),
        identity={"modbus": {"vendor": "Schneider", "model": "TM241", "firmware": "2.1"}},
        errors=("102: timeout",),
    )


def result_with(
    *hosts: HostResult, site="Plant A", started="2026-08-18T09:00:00+00:00"
) -> ScanResult:
    plan = ScanPlan(
        site=site,
        cidrs=("10.0.0.0/29",),
        profile="inventory",
        authorization=Authorization(approved_by="J. Controls", ticket="CHG-91"),
    )
    return ScanResult(
        plan=plan,
        hosts=hosts,
        verdict=VERDICT_OK,
        wire_summary={"tcp_connect": 16, "modbus_fc43": 1},
        notes=("one note",),
        started_at=started,
        finished_at="2026-08-18T09:00:31+00:00",
    )


class TestIdempotence:
    def test_the_same_scan_saved_twice_is_one_survey(self, db):
        """Appending instead would make the next comparison report change that
        never happened."""
        result = result_with(plc())
        first = save_scan(result, db)
        second = save_scan(result, db)
        assert first == second
        assert len(list_scans(db)) == 1
        assert len(load_scan(first, db)["hosts"]) == 1

    def test_re_saving_replaces_hosts_rather_than_duplicating_them(self, db):
        scan_id = save_scan(result_with(plc(), plc("10.0.0.4")), db)
        save_scan(result_with(plc()), db)  # same plan+start, fewer hosts
        stored = load_scan(scan_id, db)
        assert [h["ip"] for h in stored["hosts"]] == ["10.0.0.3"]
        assert stored["host_count"] == 1

    def test_a_different_run_is_a_different_scan(self, db):
        save_scan(result_with(plc(), started="2026-08-18T09:00:00+00:00"), db)
        save_scan(result_with(plc(), started="2026-08-18T10:00:00+00:00"), db)
        assert len(list_scans(db)) == 2

    def test_the_id_is_content_addressed_not_random(self):
        one = result_with(plc())
        assert scan_id_for(one) == scan_id_for(result_with(plc()))
        assert scan_id_for(one) != scan_id_for(result_with(plc(), site="Plant B"))


class TestFlatIdentityColumns:
    def test_the_device_table_is_a_select_not_a_program(self, db):
        """The point of the flat columns: the inventory a person reads comes out
        of one query."""
        scan_id = save_scan(result_with(plc()), db)
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT ip, mac, vendor, model, firmware, open_ports, confirmed "
                "FROM scan_hosts WHERE scan_id = ?",
                (scan_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row == (
            "10.0.0.3",
            "00:0c:29:45:3b:d8",
            "Schneider",
            "TM241",
            "2.1",
            "502",
            "modbus",
        )

    def test_only_open_ports_are_denormalized(self, db):
        """A filtered port is not a service. The full port list stays in JSON."""
        scan_id = save_scan(result_with(plc()), db)
        host = load_scan(scan_id, db)["hosts"][0]
        assert host["open_ports"] == [502]
        assert {p["port"] for p in host["ports"]} == {102, 502}

    def test_two_protocols_do_not_produce_a_device_that_does_not_exist(self, db):
        """A Modbus vendor beside an OPC-UA model is not a row anyone can act
        on. One protocol supplies the flat columns and the row says which."""
        gateway = HostResult(
            ip="10.0.0.7",
            ports=(PortResult(502, PORT_OPEN), PortResult(4840, PORT_OPEN)),
            protocols=(
                ProtocolCandidate("modbus", CONF_CONFIRMED, "modbus_fc43", ""),
                ProtocolCandidate("opcua", CONF_CONFIRMED, "opcua_getendpoints", ""),
            ),
            identity={
                "modbus": {"vendor": "Moxa"},
                "opcua": {"name": "Gateway", "model": "urn:other:thing"},
            },
        )
        scan_id = save_scan(result_with(gateway), db)
        host = load_scan(scan_id, db)["hosts"][0]
        assert host["identity_from"] == "modbus"
        assert host["vendor"] == "Moxa"
        assert host["model"] == "", "a second protocol's model must not be grafted on"
        # Nothing observed is lost.
        assert host["identity"]["opcua"]["name"] == "Gateway"

    def test_an_unconfirmed_protocol_supplies_no_identity(self, db):
        """port_only means nobody said what it is. The columns stay blank rather
        than borrowing a guess.

        The identity dict here is deliberately POPULATED. An empty one would let
        this test pass even if unconfirmed protocols were promoted, because there
        would be nothing to promote — the store must refuse the fields, not
        merely fail to find any.
        """
        guess = HostResult(
            ip="10.0.0.8",
            ports=(PortResult(502, PORT_OPEN),),
            protocols=(ProtocolCandidate("modbus", CONF_PORT_ONLY, "tcp_open", ""),),
            identity={"modbus": {"vendor": "GUESSED", "model": "GUESSED"}},
        )
        scan_id = save_scan(result_with(guess), db)
        host = load_scan(scan_id, db)["hosts"][0]
        assert host["identity_from"] == ""
        assert all(host[column] == "" for column in IDENTITY_COLUMNS)
        assert host["confirmed"] == []
        # Refused for the flat row, still recorded in full.
        assert host["identity"]["modbus"]["vendor"] == "GUESSED"

    def test_a_confirmed_protocol_with_no_fields_falls_through(self, db):
        """FC43 answered 'illegal function': confirmed, identity unknown. The
        columns must not be filled from the next protocol either."""
        host = HostResult(
            ip="10.0.0.9",
            ports=(PortResult(502, PORT_OPEN),),
            protocols=(ProtocolCandidate("modbus", CONF_CONFIRMED, "modbus_fc43:rejected", ""),),
            identity={},
        )
        scan_id = save_scan(result_with(host), db)
        stored = load_scan(scan_id, db)["hosts"][0]
        assert stored["confirmed"] == ["modbus"]
        assert stored["identity_from"] == ""
        assert stored["vendor"] == ""


class TestWhatIsPreserved:
    def test_the_plan_authorization_and_verdict_survive(self, db):
        scan_id = save_scan(result_with(plc()), db)
        stored = load_scan(scan_id, db)
        assert stored["approved_by"] == "J. Controls"
        assert stored["ticket"] == "CHG-91"
        assert stored["verdict"] == VERDICT_OK
        assert stored["scope"]["cidrs"] == ["10.0.0.0/29"]

    def test_the_wire_summary_survives_intact(self, db):
        """This is the trust page. Losing or rounding it loses the report's
        entire claim."""
        scan_id = save_scan(result_with(plc()), db)
        assert load_scan(scan_id, db)["wire_summary"] == {"tcp_connect": 16, "modbus_fc43": 1}

    def test_notes_and_per_host_errors_survive(self, db):
        scan_id = save_scan(result_with(plc()), db)
        stored = load_scan(scan_id, db)
        assert stored["notes"] == ["one note"]
        assert stored["hosts"][0]["errors"] == ["102: timeout"]

    def test_a_host_that_is_alive_but_speaks_nothing_is_still_stored(self, db):
        """It refused every port. That is a finding, and dropping it would make
        the next scan report it as a new device."""
        quiet = HostResult(ip="10.0.0.5", sources=("tcp",), ports=(PortResult(502, PORT_REFUSED),))
        scan_id = save_scan(result_with(quiet), db)
        stored = load_scan(scan_id, db)["hosts"][0]
        assert stored["alive"] is True
        assert stored["confirmed"] == []

    def test_device_count_counts_devices_not_hosts(self, db):
        quiet = HostResult(ip="10.0.0.5", ports=(PortResult(502, PORT_REFUSED),))
        scan_id = save_scan(result_with(plc(), quiet), db)
        stored = load_scan(scan_id, db)
        assert stored["host_count"] == 2
        assert stored["device_count"] == 1

    def test_identity_json_is_valid_even_for_odd_values(self, db):
        odd = HostResult(
            ip="10.0.0.6",
            ports=(PortResult(502, PORT_OPEN),),
            protocols=(ProtocolCandidate("modbus", CONF_CONFIRMED, "modbus_fc43", ""),),
            identity={"modbus": {"vendor": "x", "extra": {"raw": object()}}},
        )
        scan_id = save_scan(result_with(odd), db)
        conn = sqlite3.connect(db)
        try:
            raw = conn.execute(
                "SELECT identity_json FROM scan_hosts WHERE scan_id = ?", (scan_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        assert json.loads(raw)["modbus"]["vendor"] == "x"


class TestListingAndLookup:
    def test_scans_list_newest_first(self, db):
        save_scan(result_with(plc(), started="2026-08-18T09:00:00+00:00"), db)
        save_scan(result_with(plc(), started="2026-08-18T11:00:00+00:00"), db)
        assert [s.started_at for s in list_scans(db)][0] == "2026-08-18T11:00:00+00:00"

    def test_an_absent_store_lists_nothing_without_creating_one(self, tmp_path):
        missing = tmp_path / "nope.db"
        assert list_scans(missing) == ()
        assert not missing.exists(), "listing must not create a database as a side effect"

    def test_an_unknown_id_is_an_error_not_an_empty_scan(self, db):
        save_scan(result_with(plc()), db)
        with pytest.raises(ScanNotFound):
            load_scan("deadbeef", db)

    def test_an_absent_store_is_an_error_not_an_empty_scan(self, tmp_path):
        """'No scan by that name' and 'nothing was ever stored' are different
        answers, and neither is 'this scan found nothing'."""
        with pytest.raises(ScanNotFound):
            load_scan("anything", tmp_path / "nope.db")


class TestRetention:
    def test_nothing_is_pruned_unless_asked(self, db):
        for hour in range(5):
            save_scan(result_with(plc(), started=f"2026-08-18T0{hour}:00:00+00:00"), db)
        assert len(list_scans(db)) == 5

    def test_pruning_keeps_the_newest_and_reports_the_count(self, db):
        for hour in range(5):
            save_scan(result_with(plc(), started=f"2026-08-18T0{hour}:00:00+00:00"), db)
        assert prune_scans(2, db) == 3
        remaining = list_scans(db)
        assert [s.started_at for s in remaining] == [
            "2026-08-18T04:00:00+00:00",
            "2026-08-18T03:00:00+00:00",
        ]

    def test_pruning_removes_the_hosts_too(self, db):
        for hour in range(3):
            save_scan(result_with(plc(), started=f"2026-08-18T0{hour}:00:00+00:00"), db)
        prune_scans(1, db)
        conn = sqlite3.connect(db)
        try:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM scan_hosts WHERE scan_id NOT IN (SELECT scan_id FROM scans)"
            ).fetchone()[0]
        finally:
            conn.close()
        assert orphans == 0

    def test_keeping_zero_is_refused(self, db):
        """Deleting every survey is not a retention policy."""
        save_scan(result_with(plc()), db)
        with pytest.raises(ValueError, match="at least 1"):
            prune_scans(0, db)
        assert len(list_scans(db)) == 1

    def test_pruning_an_absent_store_is_harmless(self, tmp_path):
        assert prune_scans(3, tmp_path / "nope.db") == 0


class TestItDoesNotDisturbTheSamplesTable:
    def test_collected_data_and_surveys_coexist_in_one_database(self, db):
        """Two products of the same box. One filling up must not corrupt the
        other, and neither may drop the other's schema."""
        from iaiops.core.sink.sqlite_local import SQLiteLocalSink

        sink = SQLiteLocalSink(db_path=db, endpoint="plc1", protocol="modbus")
        sink.write([{"metric": "temp", "value": 21.5, "numeric": True, "timestamp": ""}])
        save_scan(result_with(plc()), db)
        sink.write([{"metric": "temp", "value": 22.0, "numeric": True, "timestamp": ""}])
        sink.close()

        conn = sqlite3.connect(db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1
        finally:
            conn.close()


class TestSectionNumbersMatchWhatIsThere:
    """A clean scan rendered `1 · 2 · 4` and looked like it was missing a section.

    `_diagnosis` renders nothing when there are no notes and no per-host errors,
    and the numbers were typed into each heading — so the BEST possible result
    produced the most suspicious-looking document, on the one artifact whose
    whole job is to be checkable against a packet capture.
    """

    def _sections(self, html: str) -> list[str]:
        return re.findall(r"<h2>(\d+) &middot; ([^<]+)</h2>", html)

    def test_a_clean_scan_numbers_consecutively(self, db):
        from iaiops.core.discovery.report import render_html

        scan_id = save_scan(result_with(plc()), db)
        record = load_scan(scan_id, db)
        record["notes"] = []
        for host in record["hosts"]:
            host["errors"] = []
        numbers = [int(n) for n, _ in self._sections(render_html(record))]
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"headings jump: {self._sections(render_html(record))}"
        )

    def test_a_scan_with_a_diagnosis_also_numbers_consecutively(self, db):
        from iaiops.core.discovery.report import render_html

        scan_id = save_scan(result_with(plc()), db)
        record = load_scan(scan_id, db)
        record["notes"] = ["something worth saying"]
        sections = self._sections(render_html(record))
        assert [int(n) for n, _ in sections] == list(range(1, len(sections) + 1))
        assert any("Diagnosis" in title for _, title in sections)

    def test_the_diagnosis_section_really_does_disappear(self, db):
        """Otherwise the test above passes for the wrong reason."""
        from iaiops.core.discovery.report import render_html

        scan_id = save_scan(result_with(plc()), db)
        record = load_scan(scan_id, db)
        record["notes"] = []
        for host in record["hosts"]:
            host["errors"] = []
        assert not any("Diagnosis" in title for _, title in self._sections(render_html(record)))

    def test_no_placeholder_survives_into_the_page(self, db):
        from iaiops.core.discovery.report import render_html

        scan_id = save_scan(result_with(plc()), db)
        assert "[[N]]" not in render_html(load_scan(scan_id, db))
