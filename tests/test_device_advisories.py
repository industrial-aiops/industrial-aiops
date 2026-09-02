"""Advisory matching, and the four words it is not allowed to say.

`scan` reads vendor / model / firmware and does nothing with them; correlating
that against published advisories is the obvious next step and the easiest place
in this product to say something false. The guards here are mostly about the
restraint rather than the matching:

* falling inside a stated range is **not** "vulnerable" or "exploitable" —
  reachability and compensating controls decide that and are invisible here;
* a firmware string that cannot be ordered is refused, not guessed into an
  ordering that would produce a confident wrong comparison;
* a device no advisory mentions is **absent**, not reported clean — the library
  is whatever the site mounted, and "nothing known" is not "nothing there".
"""

from __future__ import annotations

import json

import pytest

from iaiops.core.brain.device_advisories import (
    IN_RANGE,
    NOT_AFFECTED,
    VERSION_UNKNOWN,
    VERSION_UNPARSED,
    load_advisories,
    match_devices,
    parse_version,
)

pytestmark = pytest.mark.unit

ADVISORY = {
    "id": "ICSA-24-012-01",
    "vendor": "Siemens",
    "model": "S7-1500",
    "affected_below": "2.9.2",
    "title": "example",
    "source": "CISA ICS advisory ICSA-24-012-01",
}


def _dev(firmware="2.8.1", vendor="Siemens", model="S7-1500", ip="10.0.0.5"):
    return {"ip": ip, "vendor": vendor, "model": model, "firmware": firmware}


# ─── matching ────────────────────────────────────────────────────────────────


def test_a_device_inside_the_stated_range_is_reported():
    out = match_devices([_dev("2.8.1")], [ADVISORY])
    assert out["summary"][IN_RANGE] == 1
    finding = out["findings"][0]
    assert finding["advisory_id"] == "ICSA-24-012-01"
    assert finding["source"].startswith("CISA")


def test_a_device_above_the_range_is_not_affected():
    out = match_devices([_dev("3.0.0")], [ADVISORY])
    assert out["findings"][0]["status"] == NOT_AFFECTED


def test_version_comparison_pads_unequal_lengths():
    out = match_devices([_dev("2.9")], [ADVISORY])
    assert out["findings"][0]["status"] == IN_RANGE  # 2.9.0 < 2.9.2


def test_a_range_with_a_lower_bound_excludes_older_firmware():
    adv = {**ADVISORY, "affected_from": "2.5.0"}
    assert match_devices([_dev("2.4.0")], [adv])["findings"][0]["status"] == NOT_AFFECTED
    assert match_devices([_dev("2.6.0")], [adv])["findings"][0]["status"] == IN_RANGE


def test_an_explicit_version_list_is_honoured():
    adv = {k: v for k, v in ADVISORY.items() if k != "affected_below"}
    adv["affected_versions"] = ["2.8.1", "2.9.0"]
    assert match_devices([_dev("2.8.1")], [adv])["findings"][0]["status"] == IN_RANGE
    assert match_devices([_dev("2.8.2")], [adv])["findings"][0]["status"] == NOT_AFFECTED


def test_vendor_and_model_match_ignores_case_and_punctuation():
    out = match_devices([_dev(vendor="SIEMENS", model="s7 1500")], [ADVISORY])
    assert out["findings"][0]["status"] == IN_RANGE


def test_a_different_model_is_not_matched():
    assert match_devices([_dev(model="S7-1200")], [ADVISORY])["findings"] == []


# ─── the honest middle states ────────────────────────────────────────────────


def test_a_device_with_no_firmware_read_is_neither_a_hit_nor_a_pass():
    out = match_devices([_dev(firmware="")], [ADVISORY])
    finding = out["findings"][0]
    assert finding["status"] == VERSION_UNKNOWN
    assert "read no firmware" in finding["detail"]


def test_an_unorderable_firmware_string_is_refused_not_guessed():
    out = match_devices([_dev(firmware="Rev C")], [ADVISORY])
    finding = out["findings"][0]
    assert finding["status"] == VERSION_UNPARSED
    assert "not compared rather than guessed" in finding["detail"]


def test_an_advisory_with_no_range_does_not_become_a_hit():
    adv = {k: v for k, v in ADVISORY.items() if k != "affected_below"}
    out = match_devices([_dev("2.8.1")], [adv])
    assert out["findings"][0]["status"] == VERSION_UNKNOWN


@pytest.mark.parametrize("raw", ["Rev C", "", "unknown", "v2.x", None])
def test_parse_version_refuses_what_it_cannot_order(raw):
    assert parse_version(raw) is None


@pytest.mark.parametrize(
    ("raw", "want"),
    [("2.9.2", (2, 9, 2)), ("V2.9", (2, 9)), ("2.9.2-rc1", (2, 9, 2))],
)
def test_parse_version_reads_what_it_can(raw, want):
    assert parse_version(raw) == want


# ─── what it must never say ──────────────────────────────────────────────────


def test_no_finding_claims_exploitability():
    """Scoped to the findings: the disclaimer is allowed to use the word to deny it."""
    out = match_devices([_dev("2.8.1")], [ADVISORY])
    findings = json.dumps(out["findings"]).lower()
    for word in ("vulnerable", "exploitable", "exploit", "cvss", "severity", "critical"):
        assert word not in findings, f"a finding used the word {word!r}"
    assert out["findings"][0]["status"] == IN_RANGE, "the strongest word it may use"
    assert "not the same as being exploitable" in out["advisory_note"]


def test_an_unmentioned_device_is_absent_not_reported_clean():
    out = match_devices([_dev(vendor="Rockwell", model="1756-L83E")], [ADVISORY])
    assert out["findings"] == []
    assert "not 'nothing there'" in out["note"]
    assert out["items_returned"] == 0


# ─── the mounted library ─────────────────────────────────────────────────────


def test_an_advisory_without_a_source_is_refused():
    adv = {k: v for k, v in ADVISORY.items() if k != "source"}
    with pytest.raises(ValueError, match="no provenance|no source"):
        match_devices([_dev()], [adv])


def test_an_advisory_without_vendor_or_model_is_refused():
    with pytest.raises(ValueError, match="id, vendor and model"):
        match_devices([_dev()], [{"id": "X", "source": "s"}])


def test_one_bad_entry_refuses_the_whole_file(tmp_path):
    path = tmp_path / "adv.json"
    path.write_text(json.dumps({"advisories": [ADVISORY, {"id": "Y", "vendor": "V"}]}), "utf-8")
    with pytest.raises(ValueError):
        load_advisories(path)


def test_a_good_file_loads(tmp_path):
    path = tmp_path / "adv.json"
    path.write_text(json.dumps({"advisories": [ADVISORY]}), "utf-8")
    assert len(load_advisories(path)) == 1


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(ValueError, match="No advisory library"):
        load_advisories(tmp_path / "nope.json")


def test_the_tool_is_governed_and_read_only():
    import mcp_server.tools.asset_tools as mod

    fn = mod.device_advisory_check
    assert getattr(fn, "_is_governed_tool", False)
    assert (fn.__doc__ or "").startswith("[READ]")
