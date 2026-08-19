"""``iaiops scan`` — the command line that makes the engine usable by a person.

The library was verified end to end long before this existed; a library that
cannot be run from a terminal cannot be shown to anyone, and this whole surface
exists for that. So the tests here are about the COMMAND, not the engine: does
the preview really send nothing, does declining really send nothing, and does a
mistake produce one teaching line instead of a traceback.

The first of those is the one that matters. ``scan plan`` promising "nothing has
been sent to the network to produce this" is the sentence an operator relies on
when they run it against a network they have not been given permission for yet.
It is asserted mechanically here — the probe and the runner are replaced with
things that raise on contact — rather than by reading the code and believing it.
"""

from __future__ import annotations

import dataclasses
import errno
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from iaiops.cli.scan import scan_app
from iaiops.core.discovery import runner as runner_mod
from iaiops.core.discovery import sweep as sweep_mod
from iaiops.core.discovery.types import PacingPolicy

pytestmark = pytest.mark.unit

runner = CliRunner()

#: Pacing for the fixtures only. The real defaults are deliberately timid; this
#: is not the place that guarantee is tested.
BRISK = PacingPolicy(
    connects_per_second=100.0, max_concurrency=8, per_host_gap_ms=0, identify_gap_ms=0
)


# ── helpers ──────────────────────────────────────────────────────────────────


class FakeSocket:
    def shutdown(self, how):  # noqa: D102
        pass

    def close(self):  # noqa: D102
        pass


def connector_for(open_ports: dict[str, set[int]]):
    """Same idea as tests/test_discovery_runner.py: named hosts open named ports."""

    def connect(address, timeout):
        host, port = address
        if port in open_ports.get(host, ()):
            return FakeSocket()
        raise OSError(errno.ECONNREFUSED, "refused")

    return connect


@pytest.fixture
def no_network(monkeypatch):
    """Make any emission a loud failure. Nothing here may touch a socket."""

    def explode(*args, **kwargs):
        raise AssertionError("this command emitted a packet — it must not")

    monkeypatch.setattr(sweep_mod, "probe_port", explode)
    monkeypatch.setattr(runner_mod, "run_scan", explode)


def _fake_identify_plan():
    """A Modbus probe that answers from memory instead of from the network.

    Injecting the connector alone is NOT enough, and the first run of this file
    proved it: the sweep went through the fake socket while the identify stage
    built a real pymodbus client and spent ten seconds timing out against
    10.0.0.3 — an address nobody here owns. A unit test that puts packets on a
    stranger's network is a bug regardless of what it asserts.
    """
    from iaiops.core.discovery import wirelog
    from iaiops.core.discovery.identify import IdentifyProbe

    def run(ip, port, timeout_s, log):
        log.record(wirelog.MODBUS_FC43, host=ip, detail=str(port))
        return {"vendor": "Schneider", "model": "TM241"}

    return {
        "modbus": IdentifyProbe(
            protocol="modbus",
            wire_kind=wirelog.MODBUS_FC43,
            rationale="test double",
            run=run,
        )
    }


@pytest.fixture
def fake_scan(monkeypatch):
    """Run the real pipeline with every network edge replaced by a double."""
    real = runner_mod.run_scan

    def patched(plan, **kwargs):
        kwargs.setdefault("connector", connector_for({"10.0.0.3": {502}}))
        kwargs.setdefault("arp_reader", lambda: ((), ()))
        kwargs.setdefault("identify_plan", _fake_identify_plan())
        # The real 250ms-per-host gap is the product being gentle, and it is
        # tested where pacing is the subject. Paying it here bought nothing but
        # 1.3 seconds per invocation.
        return real(dataclasses.replace(plan, pacing=BRISK), **kwargs)

    monkeypatch.setattr(runner_mod, "run_scan", patched)


def out_json(result):
    return json.loads(result.output)


# ── the preview really sends nothing ─────────────────────────────────────────


class TestPlanEmitsNothing:
    def test_the_preview_touches_no_socket(self, no_network):
        """The sentence `scan plan` prints about itself, asserted mechanically."""
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29"])
        assert result.exit_code == 0, result.output

    def test_it_says_so_in_the_output(self, no_network):
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29"])
        assert "nothing has been sent" in result.output.lower()

    def test_it_lists_what_would_be_touched(self, no_network):
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29"])
        for expected in ("Hosts in scope", "Ports per host", "502", "Worst-case time"):
            assert expected in result.output

    def test_it_lists_what_is_never_done(self, no_network):
        """The absences are the half that makes the counts mean anything."""
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29"])
        assert "will NOT" in result.output
        assert "No writes of any kind" in result.output

    def test_the_json_form_is_machine_readable(self, no_network):
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29", "--json"])
        assert result.exit_code == 0, result.output
        assert out_json(result)["emits_packets"] is True

    def test_a_passive_plan_declares_zero_emissions(self, no_network):
        result = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--profile", "passive", "--json"]
        )
        assert out_json(result)["emits_packets"] is False


class TestPlanFileOutput:
    def test_a_json_suffix_gets_json(self, no_network, tmp_path):
        """The file's format follows its SUFFIX, not the ``--json`` flag.

        Tying it to the flag meant `--out preview.json` wrote plain text under a
        .json name — an extension that lies about its contents.
        """
        path = tmp_path / "preview.json"
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29", "--out", str(path)])
        assert result.exit_code == 0, result.output
        assert json.loads(path.read_text())["profile"]["name"] == "inventory"

    def test_a_txt_suffix_gets_text(self, no_network, tmp_path):
        path = tmp_path / "preview.txt"
        runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29", "--out", str(path)])
        assert path.read_text().startswith("SCAN PREVIEW")

    def test_the_json_flag_does_not_change_the_file_format(self, no_network, tmp_path):
        """The flag is about stdout. The file's format follows its suffix, so a
        script asking for both does not get a surprise."""
        path = tmp_path / "preview.txt"
        runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29", "--json", "--out", str(path)])
        assert path.read_text().startswith("SCAN PREVIEW")

    def test_traversal_is_refused(self, no_network, tmp_path):
        result = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--out", "../escape.txt"]
        )
        assert result.exit_code == 1
        assert "traversal" in result.output


class TestProtocolHints:
    """``--protocols`` may only ever NARROW what gets touched.

    This flag sits on top of a bug that was fixed underneath it: any hint used
    to flip ``include_optional`` on, so ``--protocols mtconnect`` turned a
    six-port inventory sweep into one that also connected to 80 and 8080 —
    ports the allowlist itself marks as ambiguous with IT. Asking for LESS
    reached further, and reached at ordinary web servers on the OT VLAN.

    The engine is fixed; these assert the property through the flag a person
    actually types, which is where it would be noticed too late.
    """

    def ports_line(self, result) -> str:
        return next(ln for ln in result.output.splitlines() if "Ports per host" in ln)

    def test_a_hint_narrows_to_that_protocols_port(self, no_network):
        result = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--protocols", "modbus"]
        )
        assert result.exit_code == 0, result.output
        assert "(502)" in self.ports_line(result)

    def test_a_hint_only_ever_removes_ports(self, no_network):
        """The hinted port set must be a SUBSET of the unhinted one.

        Note what this does not do: it cannot catch the widening regression.
        With ``--protocols modbus`` the widening adds 80 and 8080 and the modbus
        filter then removes them again, so the final line is identical either
        way. The regression is caught by the opt-in test below, which is the
        only place it is observable from the command line. Named for what it
        actually checks rather than for what would be nicer to claim.
        """
        plain = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/29", "--json"])
        hinted = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--protocols", "modbus", "--json"]
        )
        plain_ports = {p["port"] for p in out_json(plain)["ports"]}
        hinted_ports = {p["port"] for p in out_json(hinted)["ports"]}
        assert hinted_ports < plain_ports, (hinted_ports, plain_ports)

    def test_an_opt_in_only_hint_is_refused_with_its_reason(self, no_network):
        """Refused rather than resolved to an empty set — sweeping nothing while
        reporting a sweep is the worst of the three options."""
        result = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--protocols", "mtconnect"]
        )
        assert result.exit_code == 1
        assert "opt-in" in result.output
        assert "Traceback" not in result.output

    def test_the_profile_is_what_unlocks_opt_in_ports(self, no_network):
        """`deep` includes them, so the same hint now resolves — the profile
        decides how far a run may reach, and the hint only narrows."""
        result = runner.invoke(
            scan_app,
            [
                "plan",
                "--targets",
                "10.0.0.0/29",
                "--protocols",
                "mtconnect",
                "--profile",
                "deep",
                "--approved-by",
                "J. Controls",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "5000" in self.ports_line(result)

    def test_a_protocol_that_is_never_scanned_is_refused_by_name(self, no_network):
        """SECS/GEM. A fab tool typically accepts ONE host connection, so an
        identify session can stop a production tool."""
        result = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--protocols", "secsgem"]
        )
        assert result.exit_code == 1
        assert "never discovered by scanning" in result.output


# ── mistakes produce one teaching line, never a traceback ────────────────────


class TestMistakesTeach:
    def _assert_teaches(self, result, needle: str):
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output
        assert needle in result.output

    def test_a_misspelled_profile_lists_the_real_ones(self, no_network):
        result = runner.invoke(
            scan_app, ["plan", "--targets", "10.0.0.0/29", "--profile", "agressive"]
        )
        self._assert_teaches(result, "legacy-safe")

    def test_no_target_says_what_a_target_looks_like(self, no_network):
        result = runner.invoke(scan_app, ["plan", "--targets", ""])
        self._assert_teaches(result, "--targets 10.0.0.0/24")

    def test_an_absurd_scope_is_refused_before_expansion(self, no_network):
        """A /8 is 16.7M addresses. Refusing it is what stops a mistyped prefix
        from becoming a very long incident."""
        result = runner.invoke(scan_app, ["plan", "--targets", "10.0.0.0/8"])
        self._assert_teaches(result, "mistyped prefix")

    def test_an_unknown_scan_id_teaches_instead_of_crashing(self, tmp_path):
        """``ScanNotFound`` is a ``LookupError``, which ``cli_errors`` did not
        catch — so a carefully written teaching message escaped as a traceback
        and the user saw nothing. The caught families now include it."""
        db = tmp_path / "data.db"
        result = runner.invoke(
            scan_app, ["report", "nosuchid", "--out", str(tmp_path / "x.html"), "--db", str(db)]
        )
        self._assert_teaches(result, "No scan has been stored yet")

    def test_reporting_from_a_store_that_has_scans_but_not_this_one(self, tmp_path, fake_scan):
        db = tmp_path / "data.db"
        runner.invoke(
            scan_app,
            ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db)],
        )
        result = runner.invoke(
            scan_app, ["report", "nosuchid", "--out", str(tmp_path / "x.html"), "--db", str(db)]
        )
        self._assert_teaches(result, "nosuchid")


# ── confirmation ─────────────────────────────────────────────────────────────


class TestConfirmation:
    def test_declining_sends_nothing(self, no_network):
        """The default path for someone about to touch a plant network."""
        result = runner.invoke(scan_app, ["run", "--targets", "10.0.0.0/29"], input="n\n")
        assert result.exit_code == 0
        assert "Nothing was sent" in result.output

    def test_the_preview_is_shown_before_asking(self, no_network):
        result = runner.invoke(scan_app, ["run", "--targets", "10.0.0.0/29"], input="n\n")
        assert "SCAN PREVIEW" in result.output
        assert result.output.index("SCAN PREVIEW") < result.output.index("Proceed")

    def test_declining_stores_nothing(self, no_network, tmp_path):
        db = tmp_path / "data.db"
        runner.invoke(scan_app, ["run", "--targets", "10.0.0.0/29", "--db", str(db)], input="n\n")
        assert not db.exists(), "a declined scan created a database"

    def test_no_answer_available_refuses_rather_than_scanning(self, no_network):
        """A pipeline or CI job that cannot answer must not be taken as a yes.

        Detected by asking and failing rather than by ``isatty()`` — a test
        harness and a piped heredoc are both non-TTYs that CAN answer, so the
        guess is wrong in both directions.
        """
        result = runner.invoke(scan_app, ["run", "--targets", "10.0.0.0/29"], input="")
        assert result.exit_code == 1, result.output
        assert "nothing was sent" in result.output.lower()
        assert "--yes" in result.output
        assert "Traceback" not in result.output

    def test_yes_skips_the_question(self, fake_scan, tmp_path):
        result = runner.invoke(
            scan_app,
            ["run", "--yes", "--targets", "10.0.0.3", "--db", str(tmp_path / "d.db")],
        )
        assert result.exit_code == 0, result.output
        assert "Proceed" not in result.output


# ── running ──────────────────────────────────────────────────────────────────


class TestRun:
    def test_a_found_device_is_reported(self, fake_scan, tmp_path):
        result = runner.invoke(
            scan_app,
            ["run", "--yes", "--targets", "10.0.0.3", "--db", str(tmp_path / "d.db")],
        )
        assert result.exit_code == 0, result.output
        payload = out_json(result)
        assert payload["hosts_seen"] >= 1
        assert payload["wire_summary"]["tcp_connect"] >= 1

    def test_the_result_is_stored_and_listable(self, fake_scan, tmp_path):
        db = tmp_path / "d.db"
        run = runner.invoke(
            scan_app,
            ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db), "--site", "Plant A"],
        )
        scan_id = out_json(run)["scan_id"]
        listed = out_json(runner.invoke(scan_app, ["list", "--db", str(db)]))
        assert [row["scan_id"] for row in listed] == [scan_id]
        assert listed[0]["site"] == "Plant A"

    def test_no_store_really_stores_nothing(self, fake_scan, tmp_path):
        db = tmp_path / "d.db"
        result = runner.invoke(
            scan_app,
            ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db), "--no-store"],
        )
        assert result.exit_code == 0, result.output
        assert not db.exists()

    def test_the_report_can_be_written_in_the_same_step(self, fake_scan, tmp_path):
        html = tmp_path / "survey.html"
        result = runner.invoke(
            scan_app,
            [
                "run",
                "--yes",
                "--targets",
                "10.0.0.3",
                "--db",
                str(tmp_path / "d.db"),
                "--report",
                str(html),
            ],
        )
        assert result.exit_code == 0, result.output
        text = html.read_text()
        assert "What this scan touched" in text
        assert "10.0.0.3" in text

    def test_a_report_path_outside_the_tree_is_refused(self, fake_scan, tmp_path):
        result = runner.invoke(
            scan_app,
            [
                "run",
                "--yes",
                "--targets",
                "10.0.0.3",
                "--db",
                str(tmp_path / "d.db"),
                "--report",
                "../escape.html",
            ],
        )
        assert result.exit_code == 1
        assert "traversal" in result.output

    def test_a_profile_needing_signoff_refuses_without_one(self, fake_scan, tmp_path):
        """Enforced by the library, not this layer — so it holds however the
        scan is started."""
        result = runner.invoke(
            scan_app,
            [
                "run",
                "--yes",
                "--targets",
                "10.0.0.3",
                "--profile",
                "standard",
                "--db",
                str(tmp_path / "d.db"),
            ],
        )
        assert result.exit_code == 1
        assert "recorded authorization" in result.output

    def test_a_recorded_signoff_rides_into_the_report(self, fake_scan, tmp_path):
        html = tmp_path / "s.html"
        runner.invoke(
            scan_app,
            [
                "run",
                "--yes",
                "--targets",
                "10.0.0.3",
                "--profile",
                "standard",
                "--approved-by",
                "J. Controls",
                "--ticket",
                "CHG-91",
                "--db",
                str(tmp_path / "d.db"),
                "--report",
                str(html),
            ],
        )
        assert "J. Controls" in html.read_text()


# ── report / list / prune ────────────────────────────────────────────────────


class TestReportListPrune:
    def test_report_defaults_to_the_most_recent_scan(self, fake_scan, tmp_path):
        db = tmp_path / "d.db"
        runner.invoke(scan_app, ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db)])
        html = tmp_path / "x.html"
        result = runner.invoke(scan_app, ["report", "--out", str(html), "--db", str(db)])
        assert result.exit_code == 0, result.output
        assert html.exists()

    def test_the_report_is_self_contained(self, fake_scan, tmp_path):
        db = tmp_path / "d.db"
        runner.invoke(scan_app, ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db)])
        html = tmp_path / "x.html"
        runner.invoke(scan_app, ["report", "--out", str(html), "--db", str(db)])
        text = html.read_text()
        assert "http://" not in text and "https://" not in text

    def test_listing_an_empty_store_returns_nothing_and_creates_nothing(self, tmp_path):
        db = tmp_path / "never.db"
        result = runner.invoke(scan_app, ["list", "--db", str(db)])
        assert out_json(result) == []
        assert not db.exists(), "listing created a database as a side effect"

    def test_prune_keeps_what_it_says(self, fake_scan, tmp_path):
        db = tmp_path / "d.db"
        for site in ("A", "B", "C"):
            runner.invoke(
                scan_app,
                ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db), "--site", site],
            )
        assert len(out_json(runner.invoke(scan_app, ["list", "--db", str(db)]))) == 3
        pruned = out_json(runner.invoke(scan_app, ["prune", "--keep", "1", "--db", str(db)]))
        assert pruned["deleted"] == 2
        assert len(out_json(runner.invoke(scan_app, ["list", "--db", str(db)]))) == 1

    def test_prune_refuses_to_delete_everything(self, fake_scan, tmp_path):
        db = tmp_path / "d.db"
        runner.invoke(scan_app, ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db)])
        result = runner.invoke(scan_app, ["prune", "--keep", "0", "--db", str(db)])
        assert result.exit_code == 1
        assert "at least 1" in result.output
        assert len(out_json(runner.invoke(scan_app, ["list", "--db", str(db)]))) == 1

    def test_the_store_is_a_normal_sqlite_file(self, fake_scan, tmp_path):
        """Queryable without this tool — the point of storing it in SQLite."""
        db = tmp_path / "d.db"
        runner.invoke(scan_app, ["run", "--yes", "--targets", "10.0.0.3", "--db", str(db)])
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute("SELECT ip, open_ports FROM scan_hosts").fetchall()
        finally:
            conn.close()
        assert ("10.0.0.3", "502") in rows


class TestProfiles:
    def test_the_menu_names_every_profile_and_its_signoff_rule(self, no_network):
        result = runner.invoke(scan_app, ["profiles"])
        assert result.exit_code == 0, result.output
        menu = out_json(result)
        assert {row["name"] for row in menu} == {
            "passive",
            "inventory",
            "standard",
            "deep",
            "legacy-safe",
        }
        by_name = {row["name"]: row for row in menu}
        assert by_name["standard"]["authorization"] == "required"
        assert by_name["inventory"]["authorization"] == "not required"

    def test_legacy_safe_is_described_as_sweep_only(self, no_network):
        """The profile that decides whether this product is ever trusted on a
        line of 1990s controllers."""
        menu = out_json(runner.invoke(scan_app, ["profiles"]))
        legacy = next(row for row in menu if row["name"] == "legacy-safe")
        assert "L2_identify" not in legacy["stages"]
