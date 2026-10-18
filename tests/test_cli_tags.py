"""`iaiops tags export|apply` — the round trip, end to end.

The engine is tested in `test_tag_sheet.py`. What matters here is that the two
halves actually meet: a sheet this command writes has to be one this command can
read back, and the patch it produces has to be something `config.yaml` accepts.

The last test is the one that would have caught a whole class of failure on its
own — it takes the emitted patch, merges it into a real config file, loads it
with the real loader, and asserts `readiness` now reports the gap as filled.
Everything before it can pass while the feature does nothing.
"""

from __future__ import annotations

import csv

import pytest
import yaml
from typer.testing import CliRunner

pytestmark = pytest.mark.unit

runner = CliRunner()

CONFIG = {
    "targets": [
        {
            "name": "line1",
            "protocol": "modbus",
            "host": "127.0.0.1",
            "port": 5020,
            "tags": [
                {"ref": "40001", "label": "GoodPartsCounter"},
                {"ref": "40002", "label": "Machine running"},
            ],
        }
    ]
}


@pytest.fixture
def cli():
    from iaiops.cli.tags import tags_app

    return tags_app


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """A real config.yaml, loaded by the real loader."""
    monkeypatch.setenv("HOME", str(tmp_path))
    home = tmp_path / ".iaiops"
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    # `IAIOPS_CONFIG` is the one override every loader honours — the module
    # constants are resolved at import time and patching them misses callers.
    monkeypatch.setenv("IAIOPS_CONFIG", str(path))
    return path


class TestExport:
    def test_it_writes_a_row_per_tag(self, cli, configured, tmp_path):
        out = tmp_path / "sheet.csv"
        result = runner.invoke(cli, ["export", str(out)])
        assert result.exit_code == 0, result.output
        rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
        assert [r["ref"] for r in rows] == ["40001", "40002"]

    def test_the_role_column_comes_out_empty(self, cli, configured, tmp_path):
        """Including beside a tag literally called `GoodPartsCounter`."""
        out = tmp_path / "sheet.csv"
        runner.invoke(cli, ["export", str(out)])
        rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
        assert all(r["role"] == "" for r in rows), rows

    def test_it_says_what_to_fill_in(self, cli, configured, tmp_path):
        result = runner.invoke(cli, ["export", str(tmp_path / "s.csv")])
        assert "run_state" in result.output and "running_when" in result.output

    def test_a_site_with_no_tags_is_told_what_to_do_first(self, tmp_path, monkeypatch, cli):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("IAIOPS_CONFIG", str(tmp_path / "nothing.yaml"))
        result = runner.invoke(cli, ["export", str(tmp_path / "s.csv")])
        assert result.exit_code != 0
        assert "scan run" in result.output

    def test_a_wrong_extension_is_refused(self, cli, configured, tmp_path):
        assert runner.invoke(cli, ["export", str(tmp_path / "s.exe")]).exit_code != 0


class TestApply:
    def _filled(self, tmp_path, cli, **roles):
        out = tmp_path / "sheet.csv"
        runner.invoke(cli, ["export", str(out)])
        rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
        for r in rows:
            if r["ref"] in roles:
                r.update(roles[r["ref"]])
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return out

    def test_a_sheet_this_command_wrote_is_one_it_can_read(self, cli, configured, tmp_path):
        sheet = self._filled(tmp_path, cli, **{"40001": {"role": "total_count"}})
        result = runner.invoke(cli, ["apply", str(sheet), "--by", "wei"])
        assert result.exit_code == 0, result.output
        assert "total_count" in result.output

    def test_an_untouched_sheet_says_nothing_was_confirmed(self, cli, configured, tmp_path):
        sheet = self._filled(tmp_path, cli)
        result = runner.invoke(cli, ["apply", str(sheet), "--by", "wei"])
        assert result.exit_code == 0
        assert "blank" in result.output.lower() or "none confirmed" in result.output.lower()

    def test_a_run_state_with_no_running_when_is_refused(self, cli, configured, tmp_path):
        sheet = self._filled(tmp_path, cli, **{"40002": {"role": "run_state"}})
        result = runner.invoke(cli, ["apply", str(sheet), "--by", "wei"])
        assert result.exit_code != 0
        assert "running_when" in result.output

    def test_an_author_is_required(self, cli, configured, tmp_path):
        sheet = self._filled(tmp_path, cli, **{"40001": {"role": "total_count"}})
        assert runner.invoke(cli, ["apply", str(sheet)]).exit_code != 0

    def test_the_patch_can_be_written_to_a_file(self, cli, configured, tmp_path):
        sheet = self._filled(tmp_path, cli, **{"40001": {"role": "total_count"}})
        out = tmp_path / "patch.yaml"
        assert (
            runner.invoke(cli, ["apply", str(sheet), "--by", "wei", "--out", str(out)]).exit_code
            == 0
        )
        assert "total_count" in out.read_text("utf-8")

    def test_a_missing_sheet_says_which_one(self, cli, configured, tmp_path):
        result = runner.invoke(cli, ["apply", str(tmp_path / "nope.csv"), "--by", "wei"])
        assert result.exit_code != 0 and "nope.csv" in result.output

    def test_config_is_not_touched(self, cli, configured, tmp_path):
        """It emits a patch. A command that silently rewrote config.yaml would
        drop the comments a site wrote for itself."""
        before = configured.read_text("utf-8")
        sheet = self._filled(tmp_path, cli, **{"40001": {"role": "total_count"}})
        runner.invoke(cli, ["apply", str(sheet), "--by", "wei"])
        assert configured.read_text("utf-8") == before


class TestTheRoundTripActuallyCloviesTheGap:
    """The test that would have caught the whole feature doing nothing.

    Everything above can pass while the patch is unusable. This one merges it
    into a real config, loads it with the real loader, and asserts `readiness`
    changes its mind.
    """

    def test_readiness_reports_the_oee_mapping_as_met_afterwards(self, cli, configured, tmp_path):
        from iaiops.core.readiness import assess

        before = assess()
        oee_before = next(c for c in before.capabilities if c.key == "oee")
        assert any(r.key == "oee_role_mapping" and not r.met for r in oee_before.requirements)

        out = tmp_path / "sheet.csv"
        runner.invoke(cli, ["export", str(out)])
        rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
        for r in rows:
            if r["ref"] == "40001":
                r["role"] = "total_count"
            if r["ref"] == "40002":
                r["role"], r["running_when"] = "run_state", "2"
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

        patch = tmp_path / "patch.yaml"
        result = runner.invoke(cli, ["apply", str(out), "--by", "wei", "--out", str(patch)])
        assert result.exit_code == 0, result.output

        # Merge the patch the way a person would: by ref, into the same tags.
        merged = yaml.safe_load(configured.read_text("utf-8"))
        by_ref = {e["ref"]: e for e in yaml.safe_load(patch.read_text("utf-8"))}
        for tag in merged["targets"][0]["tags"]:
            tag.update(by_ref.get(tag["ref"], {}))
        configured.write_text(yaml.safe_dump(merged), encoding="utf-8")

        after = assess()
        oee_after = next(c for c in after.capabilities if c.key == "oee")
        mapping = next(r for r in oee_after.requirements if r.key == "oee_role_mapping")
        assert mapping.met, mapping.detail


class TestSuggestionStamp:
    """`export --suggest` → edit → `apply`, through the real commands and a real CSV.

    The device walk is replaced (no OPC UA server here); everything from the
    hint onward — stamping, the key file, the CSV, the verification — is real.
    """

    HINT = {
        "role": "run_state",
        "running_when": [3],
        "spec": "OPC 40001-1",
        "instance_type": "MachineryItemState_StateMachineType",
        "browse_path": "Press/MachineryItemState/CurrentState/Number",
        "node_id": "ns=2;i=7",
        "why": "Executing = 3",
    }

    def _export(self, cli, tmp_path, monkeypatch):
        import iaiops.cli.tags as tags_cli

        monkeypatch.setattr(
            tags_cli, "_suggestions", lambda config: {("line1", "40002"): self.HINT}
        )
        out = tmp_path / "sheet.csv"
        result = runner.invoke(cli, ["export", str(out), "--suggest"])
        assert result.exit_code == 0, result.output
        return out, list(csv.DictReader(out.open(newline="", encoding="utf-8")))

    def _apply(self, cli, out, rows):
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = runner.invoke(cli, ["apply", str(out), "--by", "alice"])
        assert result.exit_code == 0, result.output
        return result.output

    def test_the_first_suggest_creates_the_site_key(self, cli, configured, tmp_path, monkeypatch):
        from iaiops.core.governance.paths import ops_path

        assert not ops_path("tag_suggestion.key").exists()
        _, rows = self._export(cli, tmp_path, monkeypatch)
        assert ops_path("tag_suggestion.key").exists()
        assert rows[1]["suggestion_stamp"].startswith("v1:") and rows[0]["suggestion_stamp"] == ""

    def test_an_untouched_acceptance_is_credited_to_the_device(
        self, cli, configured, tmp_path, monkeypatch
    ):
        out, rows = self._export(cli, tmp_path, monkeypatch)
        rows[1].update(role="run_state", running_when="3")
        output = self._apply(cli, out, rows)
        assert "1 companion_spec" in output and "unverified" not in output

    def test_typed_suggestion_columns_are_credited_to_the_person(
        self, cli, configured, tmp_path, monkeypatch
    ):
        out, rows = self._export(cli, tmp_path, monkeypatch)
        rows[0].update(
            suggested_role="good_count",
            suggestion_evidence="OPC 40001-1: typed by hand",
            role="good_count",
        )
        output = self._apply(cli, out, rows)
        assert "1 companion_spec_unverified" in output
        assert "missing" in output and "Re-export" in output

    def test_a_deleted_key_downgrades_and_does_not_refuse(
        self, cli, configured, tmp_path, monkeypatch
    ):
        from iaiops.core.governance.paths import ops_path

        out, rows = self._export(cli, tmp_path, monkeypatch)
        ops_path("tag_suggestion.key").unlink()
        rows[1].update(role="run_state", running_when="3")
        output = self._apply(cli, out, rows)
        assert "1 companion_spec_unverified" in output and "no_key" in output
        assert not ops_path("tag_suggestion.key").exists()  # apply never mints a key

    def test_a_damaged_key_stops_export_with_the_reason(
        self, cli, configured, tmp_path, monkeypatch
    ):
        """Stamping with a key that is not one would void the sheet; say so, plainly."""
        from iaiops.core.governance.paths import ops_path

        ops_path("tag_suggestion.key").parent.mkdir(parents=True, exist_ok=True)
        ops_path("tag_suggestion.key").write_bytes(b"short")
        import iaiops.cli.tags as tags_cli

        monkeypatch.setattr(tags_cli, "_suggestions", lambda config: {})
        result = runner.invoke(cli, ["export", str(tmp_path / "s.csv"), "--suggest"])
        assert result.exit_code == 1
        said = " ".join(result.output.split())
        assert "not a suggestion stamp key" in said and "Delete it" in said
        assert isinstance(result.exception, SystemExit)  # a teaching line, not a traceback
